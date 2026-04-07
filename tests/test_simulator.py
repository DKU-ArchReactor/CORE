"""
simulator 모듈 테스트.
5단계별 JSON 스냅샷이 올바르게 생성되는지 검증한다.
"""

from app.state import create_state, GLOBAL_DICT
from app.simulator import core_single_tick, run_simulation


def setup_function():
    """각 테스트 전에 GLOBAL_DICT를 초기화한다."""
    GLOBAL_DICT.clear()


def test_single_tick_stages_structure():
    """스냅샷에 5단계(IF/ID/EX/MEM/WB)가 모두 포함되는지 확인."""
    create_state("u1", ["addi x1, x0, 42"])
    snapshot = core_single_tick("u1")

    assert snapshot is not None
    assert "stages" in snapshot
    for stage in ("IF", "ID", "EX", "MEM", "WB"):
        assert stage in snapshot["stages"]


def test_if_stage():
    create_state("u1", ["addi x1, x0, 10"])
    snapshot = core_single_tick("u1")

    stage_if = snapshot["stages"]["IF"]
    assert stage_if["pc"] == 0
    assert stage_if["instruction"] == "addi x1, x0, 10"


def test_id_stage():
    create_state("u1", ["addi x1, x0, 10"])
    snapshot = core_single_tick("u1")

    stage_id = snapshot["stages"]["ID"]
    assert stage_id["op"] == "addi"
    assert stage_id["rd"] == 1
    assert stage_id["imm"] == 10
    assert stage_id["controls"]["reg_write"] is True


def test_ex_stage():
    create_state("u1", ["addi x1, x0, 10"])
    snapshot = core_single_tick("u1")

    stage_ex = snapshot["stages"]["EX"]
    assert stage_ex["alu_result"] == 10


def test_mem_stage_no_access():
    create_state("u1", ["addi x1, x0, 10"])
    snapshot = core_single_tick("u1")

    stage_mem = snapshot["stages"]["MEM"]
    assert stage_mem["accessed"] is False
    assert stage_mem["operation"] == "none"


def test_wb_stage():
    create_state("u1", ["addi x1, x0, 42"])
    snapshot = core_single_tick("u1")

    stage_wb = snapshot["stages"]["WB"]
    assert stage_wb["reg_write"] is True
    assert stage_wb["rd"] == 1
    assert stage_wb["write_data"] == 42


def test_run_simulation_full():
    """전체 시뮬레이션이 올바르게 실행되고 결과가 JSON 구조인지 확인."""
    create_state("u1", [
        "addi x1, x0, 10",
        "addi x2, x0, 20",
        "add x3, x1, x2",
    ])
    result = run_simulation("u1")

    assert result["status"] == "success"
    assert result["summary"]["instructions_executed"] == 3
    assert len(result["history"]) == 3

    # x3 = 10 + 20 = 30
    final_regs = result["history"][-1]["registers"]
    assert final_regs[3] == 30


def test_load_store_stages():
    """Load/Store 시 MEM 스테이지가 올바르게 기록되는지 확인."""
    create_state("u1", [
        "addi x1, x0, 99",
        "sw x1, 0(x0)",
        "lw x2, 0(x0)",
    ])
    result = run_simulation("u1")

    # sw 스냅샷
    sw_mem = result["history"][1]["stages"]["MEM"]
    assert sw_mem["accessed"] is True
    assert sw_mem["operation"] == "store"
    assert sw_mem["write_data"] == 99

    # lw 스냅샷
    lw_mem = result["history"][2]["stages"]["MEM"]
    assert lw_mem["accessed"] is True
    assert lw_mem["operation"] == "load"
    assert lw_mem["read_data"] == 99

    # x2 == 99
    assert result["history"][-1]["registers"][2] == 99


def test_halt_returns_none():
    """모든 명령어 실행 후 None을 반환하는지 확인."""
    create_state("u1", ["addi x1, x0, 1"])
    core_single_tick("u1")
    assert core_single_tick("u1") is None
