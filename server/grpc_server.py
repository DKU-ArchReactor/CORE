"""archreactor.v1 server adapter for BE; CPU execution is process-isolated."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc

from archreactor.v1 import simulation_pb2 as pb, simulation_pb2_grpc as rpc
from app.engine_common import HISTORY_SCHEMA_VERSION
from server.limits import MAX_CONCURRENT, MAX_CYCLES, MAX_ELF, MAX_RESULT, WORKER_TIMEOUT_SECONDS

ROOT = Path(__file__).resolve().parents[1]


class Simulator(rpc.SimulatorServicer):
    def __init__(self):
        self.slots = threading.BoundedSemaphore(MAX_CONCURRENT)

    def _execute(self, payload, context):
        deadline = time.monotonic() + min(WORKER_TIMEOUT_SECONDS, context.time_remaining() or WORKER_TIMEOUT_SECONDS)
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
        process = subprocess.Popen([sys.executable, '-m', 'server.worker'], cwd=ROOT,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options)
        data = json.dumps(payload).encode('utf-8')
        try:
            while True:
                if not context.is_active():
                    context.abort(grpc.StatusCode.CANCELLED, 'Request cancelled')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, 'CORE execution timed out')
                try:
                    stdout, _ = process.communicate(input=data, timeout=min(0.05, remaining))
                    break
                except subprocess.TimeoutExpired:
                    data = None
            if process.returncode:
                context.abort(grpc.StatusCode.INTERNAL, 'CORE worker exited unexpectedly')
            try:
                response = json.loads(stdout)
            except (ValueError, UnicodeError):
                context.abort(grpc.StatusCode.INTERNAL, 'Invalid CORE worker response')
            if 'error' in response:
                code = {'RESOURCE_EXHAUSTED': grpc.StatusCode.RESOURCE_EXHAUSTED,
                        'INVALID_ARGUMENT': grpc.StatusCode.INVALID_ARGUMENT}.get(response['error'], grpc.StatusCode.INTERNAL)
                context.abort(code, response['message'])
            return response
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=0.25)
                except subprocess.TimeoutExpired:
                    process.kill()
            process.communicate()

    def RunSimulation(self, request, context):
        if not request.request_id or len(request.request_id) > 128:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'request_id is required (max 128 characters)')
        if request.mode not in (pb.SINGLE, pb.PIPELINE) or not 1 <= request.max_cycles <= MAX_CYCLES:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Invalid mode or max_cycles')
        if not request.elf:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'ELF is required')
        if len(request.elf) > MAX_ELF:
            context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, 'ELF exceeds 256 KiB')
        if not self.slots.acquire(blocking=False):
            context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, 'CORE is at capacity')
        execution_id = str(uuid.uuid4())
        try:
            response = self._execute({
                'execution_id': execution_id, 'elf': base64.b64encode(request.elf).decode('ascii'),
                'mode': 'single' if request.mode == pb.SINGLE else 'pipeline', 'max_cycles': request.max_cycles,
            }, context)
            result_json = json.dumps(response['result'], ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
            result = pb.RunSimulationResponse(
                request_id=request.request_id, execution_id=execution_id,
                status=pb.ExecutionStatus.Value(response['execution_status']),
                core_version=os.environ.get('CORE_VERSION', 'development'),
                result_schema_version=HISTORY_SCHEMA_VERSION, result_json=result_json,
            )
            if result.ByteSize() > MAX_RESULT:
                context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, 'CORE response exceeds 8 MiB')
            return result
        finally:
            self.slots.release()


def create_server():
    server = grpc.server(ThreadPoolExecutor(max_workers=MAX_CONCURRENT + 2), options=[
        ('grpc.max_receive_message_length', MAX_ELF + 1024),
        ('grpc.max_send_message_length', MAX_RESULT),
    ])
    rpc.add_SimulatorServicer_to_server(Simulator(), server)
    service = health.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(service, server)
    for name in ('', 'archreactor.v1.Simulator'):
        service.set(name, health_pb2.HealthCheckResponse.SERVING)
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=50051)
    args = parser.parse_args()
    server = create_server()
    if not server.add_insecure_port(f'{args.host}:{args.port}'):
        raise RuntimeError('Cannot bind CORE gRPC port')
    server.start()
    print(f'CORE gRPC ready on {args.host}:{args.port}', flush=True)
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        server.stop(2).wait()


if __name__ == '__main__':
    main()
