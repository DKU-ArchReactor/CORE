"""One isolated interpreter per request. Never executes ELF natively."""
import json
import os
import signal
import sys
import time
from io import BytesIO

from elftools.elf.elffile import ELFFile
from archreactor_contract.v1 import simulation_pb2 as pb

MAX_ELF = 256 * 1024
MAX_RESULT = 8 * 1024 * 1024
MAX_LOADED = 64 * 1024


def validate_elf(data):
    if not data.startswith(b'\x7fELF'):
        raise ValueError('ELF_REQUIRED')
    elf = ELFFile(BytesIO(data))
    if elf.elfclass != 32 or not elf.little_endian or elf['e_machine'] != 'EM_RISCV' or elf['e_type'] != 'ET_EXEC':
        raise ValueError('RV32IM_EXECUTABLE_REQUIRED')
    if elf['e_flags'] & 0x7:
        raise ValueError('COMPRESSED_OR_FLOAT_ABI_UNSUPPORTED')
    sections = list(elf.iter_sections())
    if any(s['sh_flags'] & 0x800 for s in sections):
        raise ValueError('COMPRESSED_SECTIONS_UNSUPPORTED')
    if sum(s['sh_size'] for s in sections if s['sh_flags'] & 2) > MAX_LOADED:
        raise ValueError('LOADED_MEMORY_LIMIT')
    text = elf.get_section_by_name('.text')
    if text is None or not text['sh_size'] or text['sh_size'] % 4:
        raise ValueError('INVALID_TEXT_SECTION')
    if elf['e_entry'] % 4 or not text['sh_addr'] <= elf['e_entry'] < text['sh_addr'] + text['sh_size']:
        raise ValueError('INVALID_ENTRY_POINT')
    # Reject sections the educational loader would otherwise silently ignore.
    supported = {'.text', '.rodata', '.data', '.sdata', '.bss', '.sbss'}
    if any(s['sh_flags'] & 2 and s['sh_size'] and s.name not in supported for s in sections):
        raise ValueError('UNSUPPORTED_ALLOCATED_SECTION')


def main():
    # A killed/expired worker loses all state; SIGTERM also executes finally.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    if sys.platform == 'linux':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (11, 12))
    from app.state import create_state, delete_state
    from app.simulator import run_simulation
    request = pb.RunSimulationRequest.FromString(sys.stdin.buffer.read(MAX_ELF + 1024))
    execution_id = sys.argv[1]
    try:
        load_start = time.perf_counter()
        validate_elf(request.elf)
        create_state(execution_id, request.elf, mode='single' if request.mode == pb.SINGLE else 'pipeline')
        load_ms = (time.perf_counter() - load_start) * 1000
        simulate_start, cpu_start = time.perf_counter(), time.process_time()
        result = run_simulation(execution_id, max_cycles=request.max_cycles)
        simulate_cpu_ms = (time.process_time() - cpu_start) * 1000
        simulate_ms = (time.perf_counter() - simulate_start) * 1000
        json_start = time.perf_counter()
        payload = json.dumps(result, separators=(',', ':'), ensure_ascii=False).encode()
        json_ms = (time.perf_counter() - json_start) * 1000
        if len(payload) > MAX_RESULT - 1024:
            raise OverflowError('RESULT_LIMIT')
        status = pb.COMPLETED if result['status'] == 'halted' else pb.SIMULATION_ERROR
        if result['status'] == 'error' and 'Execution clock limit exceeded' in result['console_output']:
            status = pb.CYCLE_LIMIT
        response = pb.RunSimulationResponse(request_id=request.request_id, execution_id=execution_id,
            status=status, result_json=payload, core_version=os.environ.get('CORE_VERSION', 'development'),
            result_schema_version=result['schema_version'])
        # Numeric diagnostics on a separate pipe keep the result contract deterministic.
        sys.stderr.write(json.dumps({'core-load': load_ms, 'core-sim': simulate_ms,
                                    'core-cpu': simulate_cpu_ms, 'core-json': json_ms}) + '\n')
        sys.stdout.buffer.write(response.SerializeToString())
    except Exception as exc:
        # No input, console output or exception details in service logs.
        # Specific classes are mapped to stable gRPC codes by the parent.
        from elftools.common.exceptions import ELFError
        code = 3 if isinstance(exc, (ValueError, ELFError)) else 8 if isinstance(exc, (OverflowError, MemoryError)) else 13
        sys.exit(code)
    finally:
        delete_state(execution_id)


if __name__ == '__main__':
    main()
