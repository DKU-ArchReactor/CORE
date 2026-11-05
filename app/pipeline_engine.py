"""Five-stage in-order engine with stalls, forwarding, and EX redirects."""

from __future__ import annotations

from typing import Optional

from app.engine_common import (
    _make_instruction_entry, _hex32, _handle_ecall, _record_runtime_error,
    _empty_cycle_events, _stage_activity_snapshot, _record_cycle,
    _access_memory, _execute_instruction,
)
from app.state import register_name


def _make_pipeline_bubble(assembly: str, status: str, flush_reason: Optional[str] = None, stall_reason: Optional[str] = None, stall_desc: Optional[str] = None) -> dict:
    return {
        "pc": 0,
        "raw_instruction": 0,
        "decoded": {
            "assembly": assembly,
            "op": "nop",
            "rd": 0,
            "rs1": 0,
            "rs2": 0,
            "imm": 0,
            "reg_write": False,
            "mem_read": False,
            "mem_write": False,
            "branch": False,
        },
        "rs1_val": None,
        "rs2_val": None,
        "alu": {
            "alu_op": "nop",
            "operand1": 0,
            "operand2": 0,
            "alu_result": 0,
        },
        "mem_read_data": None,
        "mem_write_data": None,
        "write_val": None,
        "status": status,
        "flush_info": {
            "is_flushed": status == "flushed",
            "reason": flush_reason,
        },
        "stall_reason": stall_reason,
        "stall_desc": stall_desc,
        "forwarding_info": {
            "has_forwarded": False,
            "forwarded_from": [],
            "forwarded_to": [],
            "target_register": [],
            "forwarded_value": [],
        },
        "forwarding_desc": None,
    }


def _is_writeback_candidate(entry: Optional[dict]) -> bool:
    return bool(entry and entry["decoded"]["reg_write"] and entry["decoded"]["rd"] != 0)


def _detect_pipeline_stall(state: dict, pipeline: dict) -> Optional[dict]:
    id_entry = pipeline["ID"]
    if id_entry is None or id_entry["decoded"]["op"] == "nop":
        return None

    rs1 = id_entry["decoded"]["rs1"]
    rs2 = id_entry["decoded"]["rs2"]

    if state["forwarding_enabled"]:
        ex_entry = pipeline["EX"]
        if ex_entry is not None and ex_entry["decoded"]["mem_read"] and _is_writeback_candidate(ex_entry):
            rd = ex_entry["decoded"]["rd"]
            if rd in (rs1, rs2):
                return {
                    "stall_reason": "load_use",
                    "stall_desc": "데이터 의존성(앞선 명령어의 결과 미반영)으로 인해 파이프라인이 1클록 정지(Stall)되었으며 EX 단계에 버블을 주입했습니다.",
                }
    else:
        # WB has already written before ID reads this clock.
        for stage_name in ("EX", "MEM"):
            entry = pipeline[stage_name]
            if _is_writeback_candidate(entry):
                rd = entry["decoded"]["rd"]
                if rd in (rs1, rs2):
                    return {
                        "stall_reason": "strict_dependency",
                        "stall_desc": "데이터 의존성(앞선 명령어의 결과 미반영)으로 인해 파이프라인이 1클록 정지(Stall)되었으며 EX 단계에 버블을 주입했습니다.",
                    }
    return None


def _compute_forwarding(state: dict, ex_entry: dict, mem_entry: Optional[dict], wb_entry: Optional[dict]) -> None:
    if ex_entry is None or ex_entry["decoded"]["op"] == "nop":
        return

    forwarding_info = {
        "has_forwarded": False,
        "forwarded_from": [],
        "forwarded_to": [],
        "target_register": [],
        "forwarded_value": [],
    }
    descriptions = []

    def try_forward(source_entry: Optional[dict], reg_num: int) -> Optional[int]:
        if not _is_writeback_candidate(source_entry):
            return None
        if source_entry["decoded"]["rd"] != reg_num:
            return None
        if source_entry["write_val"] is not None:
            return source_entry["write_val"]
        if source_entry["alu"] is not None:
            return source_entry["alu"]["alu_result"]
        return None

    for operand in ("rs1", "rs2"):
        reg_num = ex_entry["decoded"][operand]
        if reg_num == 0:
            continue

        forwarded_value = None
        source = None
        if mem_entry is not None:
            forwarded_value = try_forward(mem_entry, reg_num)
            if forwarded_value is not None:
                source = "EX/MEM"
        if forwarded_value is None and wb_entry is not None:
            forwarded_value = try_forward(wb_entry, reg_num)
            if forwarded_value is not None:
                source = "MEM/WB"

        if forwarded_value is not None and source is not None:
            if operand == "rs1":
                ex_entry["rs1_val"] = forwarded_value
            else:
                ex_entry["rs2_val"] = forwarded_value
            forwarding_info["has_forwarded"] = True
            forwarding_info["forwarded_from"].append(source)
            forwarding_info["forwarded_to"].append(operand)
            forwarding_info["target_register"].append(register_name(reg_num))
            forwarding_info["forwarded_value"].append(_hex32(forwarded_value))
            descriptions.append(
                f"{source} 버퍼에 대기 중인 {register_name(reg_num)} 레지스터의 최신 값({_hex32(forwarded_value)})을 EX 단계의 {operand} 입력값으로 우회 공급(Forwarding)했습니다."
            )
            state["stats"]["forwards"] += 1

    if forwarding_info["has_forwarded"]:
        ex_entry["forwarding_info"] = forwarding_info
        ex_entry["forwarding_desc"] = " ".join(descriptions)


def _has_active_pipeline(state: dict) -> bool:
    return any(state["pipeline_regs"][stage] is not None for stage in ("IF", "ID", "EX", "MEM", "WB"))


def _fetch_pipeline_entry(state: dict) -> Optional[dict]:
    if state["pc"] not in state["imem"]:
        return None
    raw_word = state["imem"][state["pc"]]
    entry = _make_instruction_entry(state["pc"], raw_word)
    state["pc"] = (state["pc"] + 4) & 0xFFFFFFFF
    return entry


def tick(state: dict) -> Optional[dict]:
    pipeline = state["pipeline_regs"]
    # The first clock performs IF rather than counting an empty setup clock.
    if state["stats"]["total_cycles"] == 0 and not _has_active_pipeline(state):
        pipeline["IF"] = _fetch_pipeline_entry(state)
        if pipeline["IF"] is None:
            state["status"] = "halted"
            return None
    branch_flush = False
    flush_reason = None
    redirect_pc = None
    cycle_events = _empty_cycle_events()

    wb_entry = pipeline["WB"]
    if wb_entry is not None and wb_entry["decoded"]["op"] != "nop":
        decoded = wb_entry["decoded"]
        if decoded["reg_write"] and decoded["rd"] != 0 and wb_entry["write_val"] is not None:
            state["regs"][decoded["rd"]] = wb_entry["write_val"] & 0xFFFFFFFF
        if decoded["op"] == "ecall":
            try:
                _handle_ecall(state)
            except ValueError as exc:
                _record_runtime_error(state, cycle_events, "WB", wb_entry, str(exc))
        if state["status"] != "error":
            state["stats"]["instructions_executed"] += 1
    if state["status"] in ("halted", "error"):
        activity = {stage: None for stage in pipeline}
        activity["WB"] = wb_entry
        state["pipeline_regs"] = {stage: None for stage in pipeline}
        return _record_cycle(state, _stage_activity_snapshot(activity), cycle_events)

    mem_entry = pipeline["MEM"]
    if state["status"] != "error" and mem_entry is not None and mem_entry["decoded"]["op"] != "nop":
        _access_memory(state, mem_entry, cycle_events)

    id_entry = pipeline["ID"]
    if state["status"] != "error" and id_entry is not None and id_entry["decoded"]["op"] != "nop":
        id_entry["status"] = "normal"
        id_entry["stall_reason"] = None
        id_entry["stall_desc"] = None
        decoded = id_entry["decoded"]
        id_entry["rs1_val"] = state["regs"][decoded["rs1"]]
        id_entry["rs2_val"] = state["regs"][decoded["rs2"]]

    ex_entry = pipeline["EX"]
    if state["status"] != "error" and ex_entry is not None and ex_entry["decoded"]["op"] != "nop":
        if state["forwarding_enabled"]:
            _compute_forwarding(state, ex_entry, mem_entry, wb_entry)
        branch_flush = _execute_instruction(state, ex_entry, cycle_events, pipelined=True)
        flush_reason = cycle_events["control_hazard"]["flush_reason"]
        redirect_pc = state["pc"]

    stall_info = None if state["status"] == "error" or branch_flush else _detect_pipeline_stall(state, pipeline)
    if stall_info is not None and pipeline["ID"] is not None:
        pipeline["ID"]["status"] = "stalled"
        pipeline["ID"]["stall_reason"] = stall_info["stall_reason"]
        pipeline["ID"]["stall_desc"] = stall_info["stall_desc"]
        cycle_events["stall"] = {
            "has_stall": True,
            "stage": "ID",
            "assembly": pipeline["ID"]["decoded"]["assembly"],
            "stall_reason": stall_info["stall_reason"],
            "stall_desc": stall_info["stall_desc"],
        }
    if ex_entry is not None and ex_entry.get("forwarding_info", {}).get("has_forwarded"):
        cycle_events["forwarding"] = {
            "has_forwarded": True,
            "stage": "EX",
            "assembly": ex_entry["decoded"]["assembly"],
            "forwarded_operand_count": len(ex_entry["forwarding_info"]["forwarded_to"]),
            "forwarding_info": ex_entry["forwarding_info"],
            "forwarding_desc": ex_entry.get("forwarding_desc"),
        }
    if branch_flush and ex_entry is not None:
        cycle_events["control_hazard"]["has_flush"] = True
        cycle_events["control_hazard"]["flush_reason"] = flush_reason
        cycle_events["control_hazard"]["redirect_pc"] = _hex32(redirect_pc if redirect_pc is not None else state["pc"])
        for stage in ("IF", "ID"):
            if pipeline[stage] is not None:
                pipeline[stage]["status"] = "flushed"
                pipeline[stage]["flush_info"] = {"is_flushed": True, "reason": flush_reason}
    stage_activity = _stage_activity_snapshot(pipeline)

    fetch_entry = None
    if state["status"] == "error":
        fetch_entry = None
    elif not state["halt_requested"]:
        if branch_flush:
            fetch_entry = None
        elif stall_info:
            fetch_entry = pipeline["IF"]
        else:
            fetch_entry = _fetch_pipeline_entry(state)
    if state["status"] == "error":
        new_pipeline = pipeline
    elif stall_info is not None:
        stall_bubble = _make_pipeline_bubble("bubble", "stalled", stall_reason=stall_info["stall_reason"], stall_desc=stall_info["stall_desc"])
        state["stats"]["stalls"] += 1
        state["stats"]["data_hazards"] += 1
        new_pipeline = {
            "WB": pipeline["MEM"],
            "MEM": pipeline["EX"],
            "EX": stall_bubble,
            "ID": pipeline["ID"],
            "IF": pipeline["IF"],
        }
        if new_pipeline["ID"] is not None:
            new_pipeline["ID"]["status"] = "normal"
    elif branch_flush:
        new_pipeline = {
            "WB": pipeline["MEM"],
            "MEM": pipeline["EX"],
            "EX": _make_pipeline_bubble("nop", "flushed", flush_reason=flush_reason),
            "ID": _make_pipeline_bubble("nop", "flushed", flush_reason=flush_reason),
            "IF": None,
        }
    else:
        new_pipeline = {
            "WB": pipeline["MEM"],
            "MEM": pipeline["EX"],
            "EX": pipeline["ID"],
            "ID": pipeline["IF"],
            "IF": fetch_entry,
        }

    state["pipeline_regs"] = new_pipeline

    if not _has_active_pipeline(state) and state["pc"] not in state["imem"] and not state["halt_requested"]:
        state["status"] = "halted"

    return _record_cycle(state, stage_activity, cycle_events)
