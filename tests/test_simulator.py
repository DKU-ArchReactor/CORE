"""
simulator 모듈 테스트.
6-part clock history 및 single/pipeline 실행이 올바른지 검증한다.
"""

from app.state import create_state, GLOBAL_DICT
from app.simulator import core_single_tick, run_simulation


def setup_function():
    GLOBAL_DICT.clear()


def test_single_cycle_history_contains_all_parts():
    elf_bytes = b"\x13\x00\x00\x00"
    create_state("u1", elf_bytes, mode="single")
    snapshot = core_single_tick("u1")

    assert snapshot is not None
    for part in ("if_stage", "id_stage", "ex_stage", "mem_stage", "wb_stage", "global_result"):
        assert part in snapshot


def test_if_stage_fields():
    elf_bytes = b"\x13\x00\x00\x00"
    create_state("u1", elf_bytes, mode="single")
    snapshot = core_single_tick("u1")

    assert snapshot["if_stage"]["pc"] == "0x00000000"
    assert snapshot["if_stage"]["raw_instruction"] == "0x00000013"
    assert snapshot["if_stage"]["status"] == "normal"


def test_global_result_registers_and_console():
    elf_bytes = b"\x13\x00\x00\x00"
    state = create_state("u1", elf_bytes, mode="single")
    result = run_simulation("u1")

    assert result["history"][-1]["global_result"]["registers"]["x0"] == "0x00000000"
    assert result["console_output"] == ""


def test_run_simulation_single_mode():
    elf_bytes = b"\x13\x00\x00\x00"
    create_state("u1", elf_bytes, mode="single")
    result = run_simulation("u1")

    assert result["status"] in ("halted", "success", "error")
    assert isinstance(result["history"], list)


def test_flush_tagging_for_jal():
    jal = (0x0000006F).to_bytes(4, "little")
    nop = (0x00000013).to_bytes(4, "little")
    create_state("u2", jal + nop, mode="pipeline")

    core_single_tick("u2")
    core_single_tick("u2")
    core_single_tick("u2")
    snapshot = core_single_tick("u2")

    assert snapshot["buffers"]["ID"]["flush_info"]["is_flushed"] is True
    assert snapshot["buffers"]["ID"]["flush_info"]["reason"] == "control_hazard_branch_taken"
    assert snapshot["id_stage"]["assembly"] == "nop"
