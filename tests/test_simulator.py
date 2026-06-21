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

    assert result["schema_version"] == "1.0"
    assert result["simulator"]["mode"] == "single"
    assert result["simulator"]["pipeline_model"] == "5-stage-in-order"
    assert result["program"]["entry_point"] == "0x00000000"
    assert result["program"]["instruction_words"] == 1
    assert result["status"] in ("halted", "success", "error")
    assert isinstance(result["history"], list)


def test_ecall_print_integer():
    program = b"".join(
        word.to_bytes(4, "little")
        for word in (
            0x02A00513,  # addi a0, zero, 42
            0x00100893,  # addi a7, zero, 1
            0x00000073,  # ecall
            0x00A00893,  # addi a7, zero, 10
            0x00000073,  # ecall
        )
    )
    create_state("u_int", program, mode="single")
    result = run_simulation("u_int")

    assert result["status"] == "halted"
    assert result["console_output"] == "42"


def test_auipc_uses_current_pc():
    state = create_state("u_auipc", b"\x13\x00\x00\x00", mode="single")
    state["entry_point"] = 0x100
    state["pc"] = 0x100
    state["imem"] = {
        0x100: 0x00001297,  # auipc x5, 0x1
    }

    result = run_simulation("u_auipc")

    assert result["status"] == "halted"
    assert state["regs"][5] == 0x1100


def test_pipeline_history_records_load_use_stall_event():
    program = b"".join(
        word.to_bytes(4, "little")
        for word in (
            0x00002283,  # lw x5, 0(x0)
            0x00128313,  # addi x6, x5, 1
        )
    )
    state = create_state("u_stall", program, mode="pipeline")
    state["dmem"][0] = 41
    result = run_simulation("u_stall")

    stall_cycles = [
        cycle for cycle in result["history"]
        if cycle["cycle_events"]["stall"]["has_stall"]
    ]

    assert state["regs"][6] == 42
    assert len(stall_cycles) == 1
    assert stall_cycles[0]["cycle_events"]["stall"]["stage"] == "ID"
    assert stall_cycles[0]["cycle_events"]["stall"]["stall_reason"] == "load_use"
    assert stall_cycles[0]["stage_activity"]["ID"]["hazard_detect"]["has_stall"] is True


def test_pipeline_history_records_forwarding_event():
    program = b"".join(
        word.to_bytes(4, "little")
        for word in (
            0x00100293,  # addi x5, zero, 1
            0x00128313,  # addi x6, x5, 1
        )
    )
    state = create_state("u_forward", program, mode="pipeline")
    result = run_simulation("u_forward")

    forwarding_cycles = [
        cycle for cycle in result["history"]
        if cycle["cycle_events"]["forwarding"]["has_forwarded"]
    ]

    assert state["regs"][6] == 2
    assert len(forwarding_cycles) == 1
    event = forwarding_cycles[0]["cycle_events"]["forwarding"]
    assert event["stage"] == "EX"
    assert event["forwarding_info"]["forwarded_from"] == ["EX/MEM"]
    assert event["forwarding_info"]["target_register"] == ["t0"]
    assert forwarding_cycles[0]["stage_activity"]["EX"]["status"] == "forwarding_active"


def test_runtime_error_records_misaligned_word_load():
    program = (0x00202283).to_bytes(4, "little")  # lw x5, 2(x0)
    create_state("u_misaligned", program, mode="single")
    result = run_simulation("u_misaligned")

    error_event = result["history"][-1]["cycle_events"]["runtime_error"]
    assert result["status"] == "error"
    assert error_event["has_error"] is True
    assert error_event["code"] == "MEMORY_ALIGNMENT_ERROR"
    assert error_event["stage"] == "MEM"
    assert error_event["assembly"] == "lw t0, 2(zero)"
    assert error_event["message"] == error_event["reason"]
    assert "4바이트 워드 정렬" in error_event["reason"]


def test_runtime_error_records_bad_string_ecall_address():
    program = b"".join(
        word.to_bytes(4, "little")
        for word in (
            0x00100513,  # addi a0, zero, 1
            0x00400893,  # addi a7, zero, 4
            0x00000073,  # ecall
        )
    )
    create_state("u_bad_ecall", program, mode="single")
    result = run_simulation("u_bad_ecall")

    error_event = result["history"][-1]["cycle_events"]["runtime_error"]
    assert result["status"] == "error"
    assert error_event["has_error"] is True
    assert error_event["code"] == "MEMORY_ALIGNMENT_ERROR"
    assert error_event["stage"] == "WB"
    assert error_event["assembly"] == "ecall"
    assert error_event["message"] == error_event["reason"]
    assert "4바이트 워드 정렬" in error_event["reason"]


def test_control_event_records_not_taken_branch_without_flush():
    program = b"".join(
        word.to_bytes(4, "little")
        for word in (
            0x00000463,  # beq zero, zero, 8
            0x00000013,  # nop
        )
    )
    create_state("u_branch_not_taken", program, mode="pipeline")
    # Make the decoded branch behave as not-taken by using bne zero, zero, 8.
    GLOBAL_DICT["u_branch_not_taken"]["imem"][0] = 0x00001463
    result = run_simulation("u_branch_not_taken")

    events = [
        cycle["cycle_events"]["control_hazard"]
        for cycle in result["history"]
        if cycle["cycle_events"]["control_hazard"]["has_control_instruction"]
    ]

    assert len(events) == 1
    assert events[0]["assembly"] == "bne zero, zero, 8"
    assert events[0]["taken"] is False
    assert events[0]["has_flush"] is False
    assert events[0]["target_pc"] == "0x00000008"
    assert events[0]["fallthrough_pc"] == "0x00000004"
    assert events[0]["flushed_stages"] == []


def test_control_event_records_taken_branch_flush_details():
    program = b"".join(
        word.to_bytes(4, "little")
        for word in (
            0x00000463,  # beq zero, zero, 8
            0x00000013,  # nop, flushed
            0x00000013,  # target nop
        )
    )
    create_state("u_branch_taken", program, mode="pipeline")
    result = run_simulation("u_branch_taken")

    events = [
        cycle["cycle_events"]["control_hazard"]
        for cycle in result["history"]
        if cycle["cycle_events"]["control_hazard"]["has_control_instruction"]
    ]

    assert len(events) == 1
    assert events[0]["assembly"] == "beq zero, zero, 8"
    assert events[0]["taken"] is True
    assert events[0]["has_flush"] is True
    assert events[0]["target_pc"] == "0x00000008"
    assert events[0]["fallthrough_pc"] == "0x00000004"
    assert events[0]["flushed_stages"] == ["IF", "ID"]
    assert events[0]["redirect_pc"] == "0x00000008"


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
