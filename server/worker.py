"""Run one request in a disposable process; never execute submitted host code."""
import base64
from io import BytesIO
import json
import sys

from elftools.elf.elffile import ELFFile
from elftools.common.exceptions import ELFError

from app.simulator import run_simulation
from app.state import create_state, delete_state
from server.limits import MAX_ELF, MAX_LOADED_MEMORY, MAX_RESULT


class ResourceLimitError(Exception):
    pass


def simulate(payload):
    data = base64.b64decode(payload['elf'], validate=True)
    if len(data) > MAX_ELF:
        raise ResourceLimitError('ELF exceeds 256 KiB')
    elf = ELFFile(BytesIO(data))
    if (elf.elfclass != 32 or not elf.little_endian or elf['e_machine'] != 'EM_RISCV'
            or elf['e_type'] != 'ET_EXEC'):
        raise ValueError('Expected a little-endian RV32 executable ELF')
    allocated = sum(section['sh_size'] for section in elf.iter_sections() if section['sh_flags'] & 2)
    if allocated > MAX_LOADED_MEMORY:
        raise ResourceLimitError('Loaded ELF memory exceeds 64 KiB')
    user_id = payload['execution_id']
    try:
        state = create_state(user_id, data, mode=payload['mode'])
        if state['pc'] % 4 or state['pc'] not in state['imem']:
            raise ValueError('ELF entry point is not a loaded, aligned instruction')
        result = run_simulation(user_id, max_cycles=payload['max_cycles'])
        if len(state['dmem']) * 4 + len(state['imem']) * 4 > MAX_LOADED_MEMORY:
            raise ResourceLimitError('Simulation memory exceeds 64 KiB')
        if result['status'] == 'halted':
            status = 'COMPLETED'
        elif (result['summary']['total_cycles'] >= payload['max_cycles']
              and not result['history'][-1]['cycle_events']['runtime_error']['has_error']):
            status = 'CYCLE_LIMIT'
        else:
            status = 'SIMULATION_ERROR'
        return {'execution_status': status, 'result': result}
    finally:
        delete_state(user_id)


def main():
    if sys.platform == 'linux':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024, 384 * 1024 * 1024))
    try:
        payload = json.loads(sys.stdin.buffer.read(MAX_ELF * 2))
        response = simulate(payload)
        encoded = json.dumps(response, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        # Leave space for protobuf envelope fields under the BE receive limit.
        if len(encoded) > MAX_RESULT - 4096:
            raise ResourceLimitError('Simulation JSON exceeds result size limit')
    except (ResourceLimitError, MemoryError):
        encoded = b'{"error":"RESOURCE_EXHAUSTED","message":"CORE resource limit exceeded"}'
    except (ELFError, ValueError, KeyError, TypeError) as exc:
        encoded = json.dumps({'error': 'INVALID_ARGUMENT', 'message': str(exc)[:1024]}).encode('utf-8')
    except Exception:
        encoded = b'{"error":"INTERNAL","message":"Unexpected CORE execution failure"}'
    sys.stdout.buffer.write(encoded)


if __name__ == '__main__':
    main()
