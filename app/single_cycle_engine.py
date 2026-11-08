"""One instruction completes IF/ID/EX/MEM/WB within a single clock."""

from app.engine_common import (
    _access_memory,
    _empty_cycle_events,
    _execute_instruction,
    _handle_ecall,
    _make_instruction_entry,
    _record_cycle,
    _record_runtime_error,
    _snapshot_stage,
)


def tick(state: dict) -> dict | None:
    pc = state["pc"]
    if pc not in state["imem"]:
        state["status"] = "halted"
        return None

    entry = _make_instruction_entry(pc, state["imem"][pc])
    decoded = entry["decoded"]
    events = _empty_cycle_events()
    activity = {stage: _snapshot_stage(stage, None) for stage in ("IF", "ID", "EX", "MEM", "WB")}
    activity["IF"] = _snapshot_stage("IF", entry)
    entry["rs1_val"] = state["regs"][decoded["rs1"]]
    entry["rs2_val"] = state["regs"][decoded["rs2"]]
    activity["ID"] = _snapshot_stage("ID", entry)

    prev_pc = pc
    state["pc"] = (pc + 4) & 0xFFFFFFFF
    _execute_instruction(state, entry, events, pipelined=False)
    activity["EX"] = _snapshot_stage("EX", entry)
    if state["status"] != "error":
        _access_memory(state, entry, events)
        activity["MEM"] = _snapshot_stage("MEM", entry)

    if state["status"] != "error":
        if decoded["op"] == "ecall":
            try:
                _handle_ecall(state)
            except ValueError as exc:
                _record_runtime_error(state, events, "WB", entry, str(exc))
        if state["status"] != "error":
            if decoded["reg_write"] and decoded["rd"] != 0:
                state["regs"][decoded["rd"]] = entry["write_val"] & 0xFFFFFFFF
            state["stats"]["instructions_executed"] += 1
        activity["WB"] = _snapshot_stage("WB", entry)

    if state["status"] != "error" and state["pc"] not in state["imem"]:
        state["status"] = "halted"
    return _record_cycle(state, activity, events, single=True, single_entry=entry, prev_pc=prev_pc)
