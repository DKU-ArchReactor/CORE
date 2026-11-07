import struct
from io import BytesIO
from unittest.mock import patch

import pytest
from elftools.elf.elffile import ELFFile
from service.worker import validate_elf
from tests.grpc.test_service import SAMPLE


def test_reject_non_riscv_and_64_bit():
    for offset, value in [(4,2),(18,62)]:
        data = bytearray(SAMPLE)
        data[offset] = value
        with pytest.raises((ValueError, Exception)):
            validate_elf(bytes(data))


def test_reject_huge_bss_before_allocating_memory():
    data = bytearray(SAMPLE)
    elf = ELFFile(BytesIO(data))
    section_index = next(i for i,s in enumerate(elf.iter_sections()) if s.name == '.text')
    # Exaggerate .text size; reject using metadata before .data() allocates.
    offset = elf['e_shoff'] + section_index * elf['e_shentsize'] + 20
    struct.pack_into('<I', data, offset, 100 * 1024 * 1024)
    with pytest.raises(ValueError, match='LOADED_MEMORY_LIMIT'):
        validate_elf(bytes(data))


def test_result_size_enforced_and_state_deleted(monkeypatch):
    import service.worker as worker
    from archreactor_contract.v1 import simulation_pb2 as pb
    from app.state import GLOBAL_DICT
    request = pb.RunSimulationRequest(request_id='bounded', elf=SAMPLE, mode=pb.PIPELINE, max_cycles=2000)
    monkeypatch.setattr(worker, 'MAX_RESULT', 1024)
    monkeypatch.setattr(worker.sys, 'argv', ['worker', 'bounded'])
    monkeypatch.setattr(worker.sys, 'stdin', type('Input', (), {'buffer':BytesIO(request.SerializeToString())})())
    # Do not apply process-level rlimits to the pytest process.
    monkeypatch.setattr(worker.sys, 'platform', 'test')
    with patch('signal.signal'), pytest.raises(SystemExit) as exc:
        worker.main()
    assert exc.value.code == 8
    assert 'bounded' not in GLOBAL_DICT
