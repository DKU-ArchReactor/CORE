"""Architectural results and clock boundaries, independent of engine internals."""

from copy import deepcopy
from pathlib import Path

import pytest

from app.simulator import core_single_tick, run_simulation
from app.state import GLOBAL_DICT, create_state


@pytest.fixture(autouse=True)
def clear_states():
    GLOBAL_DICT.clear()
    yield
    GLOBAL_DICT.clear()


def program(*words):
    return b"".join(word.to_bytes(4, "little") for word in words)


def test_single_tick_completes_one_instruction_and_freezes_history():
    state = create_state("single", program(0x00500293, 0x00128313))
    first = core_single_tick("single")  # x5 = 5
    frozen = deepcopy(first)
    assert first["global_result"]["registers"]["x5"] == "0x00000005"
    assert first["wb_stage"]["final_write_data"] == "0x00000005"
    assert first["global_result"]["metrics"]["accumulated_instructions"] == 1
    assert all(stage["assembly"] == "addi t0, zero, 5" for stage in first["stage_activity"].values())
    assert all(buffer is None for buffer in first["buffers"].values())

    second = core_single_tick("single")  # x6 = x5 + 1
    assert second["global_result"]["registers"]["x6"] == "0x00000006"
    assert second["id_stage"]["decoded_fields"]["rs1"]["current_value"] == "0x00000005"
    assert first == frozen
    assert state["stats"]["total_cycles"] == 2
    assert state["stats"]["instructions_executed"] == 2
    assert state["status"] == "halted"
    stopped = deepcopy(state)
    assert core_single_tick("single") is None
    assert state == stopped


@pytest.mark.parametrize("mode", ["single", "pipeline"])
def test_halt_does_not_execute_younger_store_or_writeback(mode):
    state = create_state(mode, program(
        0x00A00893,  # a7 = exit
        0x00000073,  # ecall
        0x00502023,  # sw x5, 0(x0), must not execute
        0x06300313,  # x6 = 99, must not execute
    ), mode=mode)
    state["regs"][5] = 42
    result = run_simulation(mode)
    assert result["status"] == "halted"
    assert state["dmem"] == {}
    assert state["regs"][6] == 0
    assert result["summary"]["instructions_executed"] == 2
    stopped = deepcopy(state)
    assert core_single_tick(mode) is None
    assert state == stopped


@pytest.mark.parametrize("mode", ["single", "pipeline"])
def test_memory_effective_address_is_unsigned_32bit(mode):
    state = create_state(mode, program(
        0x800002B7,  # lui x5, 0x80000
        0x0002A303,  # lw x6, 0(x5)
        0x0062A223,  # sw x6, 4(x5)
    ), mode=mode)
    state["dmem"][0x80000000] = 42
    result = run_simulation(mode)
    assert result["status"] == "halted"
    assert state["regs"][6] == 42
    assert state["dmem"][0x80000004] == 42
    assert all(address >= 0 for address in state["dmem"])


def test_pipeline_does_not_stall_on_immediate_bits_that_look_like_rs2():
    # The immediate 5 in addi is not a read of x5.
    state = create_state("pipe", program(0x00002283, 0x00500313), mode="pipeline")
    state["dmem"][0] = 41
    result = run_simulation("pipe")
    assert state["regs"][6] == 5
    assert result["summary"]["stalls"] == 0
    assert result["summary"]["forwards"] == 0


@pytest.mark.parametrize("forwarding", [True, False])
def test_taken_branch_flush_wins_over_wrong_path_load_dependency(forwarding):
    # A taken branch in EX and a dependent instruction in ID must redirect,
    # even when forwarding is disabled and the branch writes a link register.
    state = create_state("pipe", program(
        0x00C002EF,  # jal x5, 12
        0x00128313,  # x6 = x5 + 1, wrong path
        0x06300393,  # x7 = 99, wrong path
        0x00700413,  # x8 = 7, target
    ), mode="pipeline")
    state["forwarding_enabled"] = forwarding
    result = run_simulation("pipe")
    assert result["status"] == "halted"
    assert state["regs"][5] == 4
    assert state["regs"][6:9] == [0, 0, 7]
    assert result["summary"]["instructions_executed"] == 2


@pytest.mark.parametrize("mode", ["single", "pipeline"])
def test_faulting_load_does_not_retire_or_write_destination(mode):
    state = create_state(mode, program(0x00202283, 0x06300313), mode=mode)
    state["regs"][5] = 17
    result = run_simulation(mode)
    assert result["status"] == "error"
    assert state["regs"][5:7] == [17, 0]
    assert result["summary"]["instructions_executed"] == 0
    assert result["history"][-1]["stage_activity"]["WB"].get("will_write_reg", False) is False


@pytest.mark.parametrize("mode", ["single", "pipeline"])
def test_syscall_uses_older_values_not_younger_register_writes(mode):
    create_state(mode, program(
        0x02A00513,  # a0 = 42
        0x00100893,  # a7 = print integer
        0x00000073,
        0x06300513,  # a0 = 99, after print
        0x00A00893,  # a7 = exit
        0x00000073,
    ), mode=mode)
    result = run_simulation(mode)
    assert result["status"] == "halted"
    assert result["console_output"] == "42"
    assert result["summary"]["instructions_executed"] == 6


def test_single_branch_has_no_pipeline_flush_or_bubbles():
    create_state("single", program(0x00000463, 0x06300293, 0x00700313))
    result = run_simulation("single")
    assert result["summary"]["total_cycles"] == 2
    assert result["summary"]["instructions_executed"] == 2
    assert result["summary"]["control_hazards"] == 0
    assert result["history"][-1]["global_result"]["registers"]["x5"] == "0x00000000"
    event = result["history"][0]["cycle_events"]["control_hazard"]
    assert event["taken"] is True
    assert event["has_flush"] is False
    assert event["flushed_stages"] == []


@pytest.mark.parametrize("mode", ["single", "pipeline"])
def test_custom_cycle_limit_is_reported_and_terminal(mode):
    create_state(mode, program(0x0000006F), mode=mode)  # jal x0, 0
    result = run_simulation(mode, max_cycles=7)
    assert result["summary"]["total_cycles"] == 7
    assert "Max: 7 clocks" in result["console_output"]
    assert core_single_tick(mode) is None


@pytest.mark.parametrize("mode", ["single", "pipeline"])
def test_faulting_syscall_is_not_retired(mode):
    create_state(mode, program(0x00100513, 0x00400893, 0x00000073), mode=mode)
    result = run_simulation(mode)
    assert result["status"] == "error"
    assert result["summary"]["instructions_executed"] == 2


@pytest.mark.parametrize("mode", ["single", "pipeline"])
@pytest.mark.parametrize("word,left,right,expected", [
    (0x006283B3, 0x7FFFFFFF, 1, 0x80000000),  # add
    (0x406283B3, 0, 1, 0xFFFFFFFF),  # sub
    (0x006293B3, 1, 31, 0x80000000),  # sll
    (0x0062A3B3, 0xFFFFFFFF, 1, 1),  # slt
    (0x0062B3B3, 0xFFFFFFFF, 1, 0),  # sltu
    (0x0062C3B3, 0xF0, 0xAA, 0x5A),  # xor
    (0x0062D3B3, 0x80000000, 31, 1),  # srl
    (0x4062D3B3, 0x80000000, 31, 0xFFFFFFFF),  # sra
    (0x0062E3B3, 0xF0, 0xAA, 0xFA),  # or
    (0x0062F3B3, 0xF0, 0xAA, 0xA0),  # and
    (0x026283B3, 0xFFFFFFFE, 3, 0xFFFFFFFA),  # mul
    (0x026293B3, 0xFFFFFFFE, 3, 0xFFFFFFFF),  # mulh
    (0x0262A3B3, 0xFFFFFFFE, 3, 0xFFFFFFFF),  # mulhsu
    (0x0262B3B3, 0xFFFFFFFF, 2, 1),  # mulhu
    (0x0262C3B3, 0xFFFFFFF9, 2, 0xFFFFFFFD),  # div, truncate toward zero
    (0x0262C3B3, 0x80000000, 0xFFFFFFFF, 0x80000000),  # div overflow
    (0x0262C3B3, 7, 0, 0xFFFFFFFF),  # div by zero
    (0x0262D3B3, 0xFFFFFFFF, 2, 0x7FFFFFFF),  # divu
    (0x0262D3B3, 7, 0, 0xFFFFFFFF),  # divu by zero
    (0x0262E3B3, 0xFFFFFFF9, 2, 0xFFFFFFFF),  # rem
    (0x0262E3B3, 0x80000000, 0xFFFFFFFF, 0),  # rem overflow
    (0x0262E3B3, 7, 0, 7),  # rem by zero
    (0x0262F3B3, 0xFFFFFFFF, 2, 1),  # remu
    (0x0262F3B3, 7, 0, 7),  # remu by zero
    (0xFFF28393, 0, 0, 0xFFFFFFFF),  # addi
    (0xFFF2A393, 0xFFFFFFFE, 0, 1),  # slti
    (0xFFF2B393, 1, 0, 1),  # sltiu
    (0xFFF2C393, 0xF0, 0, 0xFFFFFF0F),  # xori
    (0xFFF2E393, 0xF0, 0, 0xFFFFFFFF),  # ori
    (0x0FF2F393, 0xFFAA, 0, 0xAA),  # andi
    (0x01F29393, 1, 0, 0x80000000),  # slli
    (0x01F2D393, 0x80000000, 0, 1),  # srli
    (0x41F2D393, 0x80000000, 0, 0xFFFFFFFF),  # srai
])
def test_instruction_results_in_each_engine(mode, word, left, right, expected):
    state = create_state(mode, program(word), mode=mode)
    state["regs"][5:7] = [left, right]
    result = run_simulation(mode)
    assert result["status"] == "halted"
    assert state["regs"][7] == expected
    assert state["regs"][0] == 0
    assert result["summary"]["instructions_executed"] == 1


@pytest.mark.parametrize("mode", ["single", "pipeline"])
@pytest.mark.parametrize("word,expected", [
    (0x00028383, 0xFFFFFF80),  # lb
    (0x00029383, 0xFFFF8080),  # lh
    (0x0002A383, 0x12348080),  # lw
    (0x0002C383, 0x80),  # lbu
    (0x0002D383, 0x8080),  # lhu
])
def test_load_width_and_signedness(mode, word, expected):
    state = create_state(mode, program(word), mode=mode)
    state["regs"][5] = 0x80000000
    state["dmem"][0x80000000] = 0x12348080
    result = run_simulation(mode)
    assert result["status"] == "halted"
    assert state["regs"][7] == expected


@pytest.mark.parametrize("mode", ["single", "pipeline"])
@pytest.mark.parametrize("word,expected", [
    (0x00628023, 0x123480AA),  # sb
    (0x00629023, 0x1234BBAA),  # sh
    (0x0062A023, 0xDDCCBBAA),  # sw
])
def test_store_width_preserves_other_bytes(mode, word, expected):
    state = create_state(mode, program(word), mode=mode)
    state["regs"][5:7] = [0x80000000, 0xDDCCBBAA]
    state["dmem"][0x80000000] = 0x12348080
    result = run_simulation(mode)
    assert result["status"] == "halted"
    assert state["dmem"][0x80000000] == expected


@pytest.mark.parametrize("mode", ["single", "pipeline"])
def test_loop_records_dynamic_instructions_and_x0_is_read_only(mode):
    # Three loop iterations: x5 = 3, 2, 1, 0. Nine dynamic instructions.
    state = create_state(mode, program(
        0x00300293,  # x5 = 3
        0xFFF28293,  # x5--
        0xFE029EE3,  # bne x5, x0, -4
        0x06300013,  # addi x0, x0, 99
        0x00000313,  # x6 = x0
    ), mode=mode)
    result = run_simulation(mode)
    assert result["status"] == "halted"
    assert state["regs"][0] == state["regs"][5] == state["regs"][6] == 0
    assert result["summary"]["instructions_executed"] == 9
    if mode == "single":
        assert result["summary"]["total_cycles"] == 9
        assert [int(c["if_stage"]["pc"], 16) for c in result["history"]] == [0, 4, 8, 4, 8, 4, 8, 12, 16]


@pytest.mark.parametrize("mode", ["single", "pipeline"])
def test_jalr_uses_old_rs1_when_destination_is_same_register(mode):
    state = create_state(mode, program(
        0x00D00293,  # x5 = 13 (jalr clears low bit)
        0x000282E7,  # jalr x5, x5, 0
        0x06300313,  # wrong path
        0x00700393,  # target: x7 = 7
    ), mode=mode)
    result = run_simulation(mode)
    assert result["status"] == "halted"
    assert state["regs"][5:8] == [8, 0, 7]
    assert result["summary"]["instructions_executed"] == 3


def test_pipeline_history_does_not_change_after_later_stall_cycles():
    state = create_state("pipe", program(0x00002283, 0x00128313), mode="pipeline")
    state["dmem"][0] = 41
    for _ in range(4):
        core_single_tick("pipe")
    earlier = deepcopy(state["history"])
    run_simulation("pipe")
    assert state["history"][:4] == earlier


@pytest.mark.parametrize("filename,expected_output", [
    ("program.elf", "ArchReactor Core Online.\nVerification Status: ALL GREEN\n"),
    ("program2.elf", "Advanced Pipeline Test Start...\nAdvanced Test Result: ALL PASS\n"),
])
def test_reference_elf_has_identical_architectural_results(filename, expected_output):
    data = Path(__file__).with_name(filename).read_bytes()
    final = []
    for mode, forwarding in [("single", False), ("pipeline", True), ("pipeline", False)]:
        state = create_state("reference", data, mode=mode)
        state["forwarding_enabled"] = forwarding
        result = run_simulation("reference")
        assert result["status"] == "halted"
        assert result["console_output"] == expected_output
        final.append((state["regs"][:], dict(state["dmem"]), result["console_output"], result["summary"]["instructions_executed"]))
        if mode == "single":
            assert result["summary"]["total_cycles"] == result["summary"]["instructions_executed"]
            assert result["summary"]["stalls"] == result["summary"]["forwards"] == 0
    assert final[0] == final[1] == final[2]


@pytest.mark.parametrize("mode", ["single", "pipeline"])
@pytest.mark.parametrize("funct3,left,right,taken", [
    (0, 5, 5, True), (0, 5, 6, False),  # beq
    (1, 5, 6, True), (1, 5, 5, False),  # bne
    (4, 0xFFFFFFFF, 1, True), (4, 1, 0xFFFFFFFF, False),  # blt
    (5, 1, 0xFFFFFFFF, True), (5, 0xFFFFFFFF, 1, False),  # bge
    (6, 1, 0xFFFFFFFF, True), (6, 0xFFFFFFFF, 1, False),  # bltu
    (7, 0xFFFFFFFF, 1, True), (7, 1, 0xFFFFFFFF, False),  # bgeu
])
def test_conditional_branch_results(mode, funct3, left, right, taken):
    branch = 0x00628463 | (funct3 << 12)  # branch x5, x6, +8
    state = create_state(mode, program(branch, 0x06300393, 0x00700413), mode=mode)
    state["regs"][5:7] = [left, right]
    result = run_simulation(mode)
    assert result["status"] == "halted"
    assert state["regs"][7:9] == [0 if taken else 99, 7]
    events = [c["cycle_events"]["control_hazard"] for c in result["history"] if c["cycle_events"]["control_hazard"]["has_control_instruction"]]
    assert len(events) == 1
    assert events[0]["taken"] is taken
    assert events[0]["has_flush"] is (taken and mode == "pipeline")


@pytest.mark.parametrize("value", [0, -1, 2001, True, 1.5])
def test_invalid_cycle_limits_are_rejected(value):
    create_state("single", program(0x00000013))
    with pytest.raises(ValueError, match="max_cycles"):
        run_simulation("single", max_cycles=value)


def test_invalid_mode_is_rejected_before_state_creation():
    with pytest.raises(ValueError, match="Unsupported simulation mode"):
        create_state("invalid", program(0x00000013), mode="other")
    assert "invalid" not in GLOBAL_DICT


@pytest.mark.parametrize("count", [1, 2, 5])
def test_pipeline_has_no_empty_setup_clock(count):
    create_state("pipe", program(*([0x00100293] * count)), mode="pipeline")
    result = run_simulation("pipe")
    assert result["summary"]["total_cycles"] == count + 4
    assert result["history"][0]["stage_activity"]["IF"]["pc"] == "0x00000000"
    assert result["history"][-1]["stage_activity"]["WB"]["pc"] == f"0x{4 * (count - 1):08X}"


def test_initial_state_and_program_metadata_are_not_execution_guesses():
    state = create_state("meta", Path(__file__).with_name("program2.elf").read_bytes())
    result = run_simulation("meta")
    assert result["initial_state"]["registers"]["x5"] == "0x00000000"
    assert result["initial_state"]["metrics"]["accumulated_instructions"] == 0
    assert len(result["program"]["instructions"]) == len(state["imem"])
    for instruction in result["program"]["instructions"]:
        assert int(instruction["raw_instruction"], 16) == state["imem"][int(instruction["pc"], 16)]
    assert any(region["name"] == ".text" and region["kind"] == "code" for region in result["program"]["memory_regions"])
    assert all(int(region["start"], 16) < int(region["end_exclusive"], 16) for region in result["program"]["memory_regions"])


@pytest.mark.parametrize("mode", ["single", "pipeline"])
def test_misaligned_instruction_target_is_an_error_not_successful_halt(mode):
    create_state(mode, program(0x00200293, 0x00028067), mode=mode)  # x5=2; jalr x0,x5,0
    result = run_simulation(mode)
    assert result["status"] == "error"
    # Errors stop immediately; an older pipeline instruction may still be in MEM.
    assert result["summary"]["instructions_executed"] == (1 if mode == "single" else 0)
    assert result["history"][-1]["cycle_events"]["runtime_error"]["code"] == "INSTRUCTION_ALIGNMENT_ERROR"


def test_writeback_is_available_to_id_without_a_stall():
    state = create_state("pipe", program(0x00500293, 0x00000013, 0x00000013, 0x00128313), mode="pipeline")
    state["forwarding_enabled"] = False
    result = run_simulation("pipe")
    assert state["regs"][6] == 6
    assert result["summary"]["stalls"] == 0


def test_wrong_path_stage_activity_is_marked_flushed():
    create_state("pipe", program(0x00000463, 0x06300293, 0x00700313), mode="pipeline")
    result = run_simulation("pipe")
    flushed = next(cycle for cycle in result["history"] if cycle["cycle_events"]["control_hazard"]["has_flush"])
    assert flushed["stage_activity"]["ID"]["status"] == "flushed"
    assert flushed["stage_activity"]["ID"]["flush_info"]["is_flushed"] is True


def test_loaded_data_word_count_does_not_include_runtime_stack_stores():
    create_state("single", program(0x00502023))
    result = run_simulation("single")
    assert result["program"]["data_words"] == 0
    assert len(result["history"][-1]["global_result"]["memory_snapshot"]) == 1


@pytest.mark.parametrize("mode", ["single", "pipeline"])
@pytest.mark.parametrize("filename", ["program.elf", "program2.elf"])
def test_every_writeback_matches_the_same_clock_register_snapshot(mode, filename):
    from app.state import REG_NAMES
    create_state("wb", Path(__file__).with_name(filename).read_bytes(), mode=mode)
    result = run_simulation("wb")
    for cycle in result["history"]:
        wb = cycle["stage_activity"]["WB"]
        if wb.get("will_write_reg"):
            register = f"x{REG_NAMES.index(wb['destination_register'])}"
            assert cycle["global_result"]["registers"][register] == wb["final_write_data"]
