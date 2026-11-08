"""Bounded unary gRPC transport around the existing simulator."""
import asyncio
import json
import logging
import math
import os
import re
import signal
import sys
import time
import uuid

import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from archreactor_contract.v1 import simulation_pb2 as pb, simulation_pb2_grpc as rpc
from service.worker import MAX_ELF, MAX_RESULT


def _extract_code_mapping(elf_bytes, result_json):
    mapping = {}
    try:
        data = json.loads(result_json)
        prog = data.get('program', {})
        if 'code_mapping' in prog and isinstance(prog['code_mapping'], dict) and prog['code_mapping']:
            mapping = {k: dict(v) for k, v in prog['code_mapping'].items()}
        else:
            for inst in prog.get('instructions', []):
                pc = inst.get('pc')
                if pc:
                    mapping[pc] = {
                        'assembly': inst.get('assembly', ''),
                        'raw_instruction': inst.get('raw_instruction', ''),
                    }
    except Exception:
        pass

    try:
        from io import BytesIO
        from elftools.elf.elffile import ELFFile
        stream = BytesIO(elf_bytes)
        elf = ELFFile(stream)
        if elf.has_dwarf_info():
            dwarfinfo = elf.get_dwarf_info()
            for cu in dwarfinfo.iter_CUs():
                lineprog = dwarfinfo.line_program_for_CU(cu)
                if lineprog is None:
                    continue
                file_entries = lineprog['file_entry'] if 'file_entry' in lineprog.header else []
                entries = lineprog.get_entries()
                prev_state = None
                for entry in entries:
                    state = entry.state
                    if state is None:
                        continue
                    if prev_state and not prev_state.end_sequence and prev_state.line > 0:
                        is_source_c = False
                        try:
                            file_idx = prev_state.file - 1
                            if 0 <= file_idx < len(file_entries):
                                f_entry = file_entries[file_idx]
                                fname = f_entry.name.decode('utf-8', errors='ignore') if hasattr(f_entry, 'name') else str(f_entry)
                                if 'source.c' in fname:
                                    is_source_c = True
                            elif not file_entries:
                                is_source_c = True
                        except Exception:
                            is_source_c = True
                        if is_source_c:
                            curr_addr = prev_state.address
                            end_addr = state.address if state.address > curr_addr else curr_addr + 4
                            while curr_addr < end_addr:
                                pc_key = f'0x{curr_addr & 0xFFFFFFFF:08X}'
                                if pc_key in mapping:
                                    mapping[pc_key]['source_line'] = prev_state.line
                                else:
                                    mapping[pc_key] = {'source_line': prev_state.line}
                                curr_addr += 4
                    prev_state = state
    except Exception:
        pass

    return mapping


class Simulator(rpc.SimulatorServicer):
    def __init__(self, concurrency=2, timeout=10.0):
        self.concurrency, self.timeout = concurrency, timeout
        self.active = 0
        self.processes = set()

    async def RunSimulation(self, request, context):
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', request.request_id):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Invalid request_id')
        if not request.elf or len(request.elf) > MAX_ELF:
            await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, 'ELF limit is 256 KiB')
        if request.mode not in (pb.SINGLE, pb.PIPELINE) or not 1 <= request.max_cycles <= 2000:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Mode or max_cycles outside v1 limits')
        # No await between checking and incrementing: atomic in the event loop.
        if self.active >= self.concurrency:
            await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, 'Simulation capacity reached')
        self.active += 1
        execution_id = str(uuid.uuid4())
        proc = None
        try:
            worker_start = time.perf_counter()
            spawn = asyncio.create_task(asyncio.create_subprocess_exec(
                sys.executable, '-m', 'service.worker', execution_id,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE))
            try:
                proc = await asyncio.shield(spawn)
            except asyncio.CancelledError:
                # Retain the process handle even if cancellation races with spawn.
                proc = await spawn
                raise
            self.processes.add(proc)
            remaining = context.time_remaining()
            timeout = min(self.timeout, remaining) if remaining is not None else self.timeout
            output, diagnostics = await asyncio.wait_for(proc.communicate(request.SerializeToString()), timeout=max(0.001, timeout))
            worker_ms = (time.perf_counter() - worker_start) * 1000
            codes = {3: grpc.StatusCode.INVALID_ARGUMENT, 8: grpc.StatusCode.RESOURCE_EXHAUSTED}
            if proc.returncode:
                await context.abort(codes.get(proc.returncode, grpc.StatusCode.INTERNAL), 'Simulation worker rejected input or exceeded resource limits')
            if len(output) > MAX_RESULT:
                await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, 'Result limit is 8 MiB')
            response = pb.RunSimulationResponse.FromString(output)
            timings = {'core-worker': worker_ms}
            try:
                measured = json.loads(diagnostics)
                for key in ('core-load', 'core-sim', 'core-cpu', 'core-json'):
                    value = float(measured[key])
                    if math.isfinite(value) and 0 <= value <= worker_ms + 1:
                        timings[key] = value
            except (ValueError, TypeError, KeyError):
                pass  # Observability must not turn a successful simulation into an error.
            context.set_trailing_metadata(tuple((key, f'{value:.3f}') for key, value in timings.items()))
            code_mapping = _extract_code_mapping(request.elf, response.result_json)
            logging.info(json.dumps({'event': 'simulation_complete', 'execution_id': execution_id,
                                     'status': response.status, 'bytes': len(output), 'timing_ms': timings,
                                     'code_mapping': code_mapping}))
            return response
        except asyncio.TimeoutError:
            await context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, 'Simulation deadline exceeded')
        finally:
            if proc is not None:
                if proc.returncode is None:
                    try:
                        proc.terminate()
                    except ProcessLookupError:
                        pass
                    try:
                        await asyncio.wait_for(proc.wait(), 0.25)
                    except asyncio.TimeoutError:
                        proc.kill()
                        await proc.wait()
                self.processes.discard(proc)
            self.active -= 1


def make_server(servicer=None):
    server = grpc.aio.server(options=[('grpc.max_receive_message_length', MAX_ELF + 1024),
                                      ('grpc.max_send_message_length', MAX_RESULT)], maximum_concurrent_rpcs=16)
    rpc.add_SimulatorServicer_to_server(servicer or Simulator(), server)
    checker = health.HealthServicer()
    checker.set('', health_pb2.HealthCheckResponse.SERVING)
    checker.set('archreactor.v1.Simulator', health_pb2.HealthCheckResponse.SERVING)
    health_pb2_grpc.add_HealthServicer_to_server(checker, server)
    return server, checker


async def main():
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    server, checker = make_server()
    server.add_insecure_port('[::]:50051')
    await server.start()
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    await stop.wait()
    checker.enter_graceful_shutdown()
    await server.stop(12)


if __name__ == '__main__':
    asyncio.run(main())
