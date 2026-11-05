"""Shared instruction semantics and immutable clock-history snapshots."""

from __future__ import annotations

from copy import deepcopy
from typing import Dict, Optional

from app.decoder import decode
from app.executor import execute
from app.memory import (
    load_byte, load_halfword, load_word, read_string,
    store_byte, store_halfword, store_word,
)
from app.state import register_name

MAX_CYCLES = 2000
HISTORY_SCHEMA_VERSION = "1.0"


def _to_s32(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - (1 << 32) if value & (1 << 31) else value


def _hex32(value: int) -> str:
    return f"0x{value & 0xFFFFFFFF:08X}"


def _snapshot_global(state: dict) -> Dict[str, object]:
    registers = {f"x{i}": _hex32(state["regs"][i]) for i in range(32)}
    memory_snapshot = { _hex32(addr): _hex32(val) for addr, val in state["dmem"].items() }
    return {
        "current_pc": _hex32(state["pc"]),
        "registers": registers,
        "memory_snapshot": memory_snapshot,
        "console_output": state["console_output"],
        "metrics": {
            "accumulated_instructions": state["stats"]["instructions_executed"],
            "accumulated_stalls": state["stats"]["stalls"],
            "accumulated_forwards": state["stats"]["forwards"],
        },
    }


def _if_stage_snapshot(pc: int, raw_word: int, assembly: str, status: str = "normal", flushed: bool = False, reason: Optional[str] = None) -> dict:
    return {
        "pc": _hex32(pc),
        "raw_instruction": _hex32(raw_word),
        "assembly": assembly,
        "status": status,
        "flush_info": {
            "is_flushed": flushed,
            "reason": reason,
        },
    }


def _id_stage_snapshot(decoded: dict, rs1_val: Optional[int], rs2_val: Optional[int], status: str = "normal", has_stall: bool = False, stall_reason: Optional[str] = None, stall_desc: Optional[str] = None) -> dict:
    rs1_hex = _hex32(rs1_val) if rs1_val is not None else "0x00000000"
    rs2_hex = _hex32(rs2_val) if rs2_val is not None else "0x00000000"
    result = {
        "assembly": decoded["assembly"],
        "status": status,
        "decoded_fields": {
            "op": decoded["op"],
            "rd": f"x{decoded['rd']}",
            "rs1": {
                "name": register_name(decoded["rs1"]),
                "num": decoded["rs1"],
                "current_value": rs1_hex,
            },
            "rs2": {
                "name": register_name(decoded["rs2"]),
                "num": decoded["rs2"],
                "current_value": rs2_hex,
            },
            "imm": decoded["imm"],
        },
        "hazard_detect": {
            "has_stall": has_stall,
            "stall_reason": stall_reason,
        },
    }
    if stall_desc is not None:
        result["stall_desc"] = stall_desc
    return result


def _ex_stage_snapshot(decoded: dict, alu: dict, forwarding_info: Optional[dict] = None, status: str = "normal", forwarding_desc: Optional[str] = None) -> dict:
    status = status if status != "normal" else ("forwarding_active" if forwarding_info and forwarding_info.get("has_forwarded") else "normal")
    result = {
        "assembly": decoded["assembly"],
        "status": status,
        "alu_operation": alu["alu_op"],
        "operand_1": _hex32(alu["operand1"]),
        "operand_2": _hex32(alu["operand2"]),
        "alu_result": _hex32(alu["alu_result"]),
        "forwarding_info": forwarding_info or {
            "has_forwarded": False,
            "forwarded_from": [],
            "forwarded_to": [],
            "target_register": [],
            "forwarded_value": [],
        },
        "flush_info": {
            "is_flushed": False,
            "reason": None,
        },
    }
    if forwarding_desc is not None:
        result["forwarding_desc"] = forwarding_desc
    return result


def _mem_stage_snapshot(decoded: dict, alu_result: int, read_data: Optional[int], write_data: Optional[int], status: str = "normal", flush_info: Optional[dict] = None) -> dict:
    return {
        "assembly": decoded["assembly"],
        "status": status,
        "flush_info": flush_info or {"is_flushed": False, "reason": None},
        "memory_operation": "load" if decoded["mem_read"] else ("store" if decoded["mem_write"] else "none"),
        "target_address": _hex32(alu_result) if decoded["mem_read"] or decoded["mem_write"] else None,
        "read_data": _hex32(read_data) if read_data is not None else None,
        "write_data": _hex32(write_data) if write_data is not None else None,
    }


def _wb_stage_snapshot(decoded: dict, write_val: Optional[int], status: str = "normal", flush_info: Optional[dict] = None) -> dict:
    return {
        "assembly": decoded["assembly"],
        "status": status,
        "flush_info": flush_info or {"is_flushed": False, "reason": None},
        "will_write_reg": decoded["reg_write"] and decoded["rd"] != 0 and status not in ("error", "flushed"),
        "destination_register": register_name(decoded["rd"]),
        "final_write_data": _hex32(write_val) if write_val is not None else None,
    }


def _make_instruction_entry(pc: int, raw_word: int) -> dict:
    decoded = decode(raw_word)
    return {
        "pc": pc,
        "raw_instruction": raw_word,
        "decoded": decoded,
        "rs1_val": None,
        "rs2_val": None,
        "alu": None,
        "mem_read_data": None,
        "mem_write_data": None,
        "write_val": None,
        "status": "normal",
        "flush_info": {
            "is_flushed": False,
            "reason": None,
        },
        "stall_reason": None,
        "stall_desc": None,
        "forwarding_info": {
            "has_forwarded": False,
            "forwarded_from": [],
            "forwarded_to": [],
            "target_register": [],
            "forwarded_value": [],
        },
        "forwarding_desc": None,
    }


def _buffer_snapshot(entry: Optional[dict]) -> Optional[dict]:
    if entry is None:
        return None
    result = {
        "pc": _hex32(entry["pc"]),
        "raw_instruction": _hex32(entry["raw_instruction"]),
        "assembly": entry["decoded"]["assembly"],
        "status": entry["status"],
        "flush_info": entry["flush_info"],
    }
    if entry.get("stall_desc") is not None:
        result["stall_info"] = {
            "stall_reason": entry.get("stall_reason"),
            "stall_desc": entry.get("stall_desc"),
        }
    if entry.get("forwarding_info", {}).get("has_forwarded"):
        result["forwarding_info"] = entry["forwarding_info"]
        result["forwarding_desc"] = entry.get("forwarding_desc")
    return result


def _empty_cycle_events() -> dict:
    return {
        "stall": {
            "has_stall": False,
            "stage": None,
            "assembly": None,
            "stall_reason": None,
            "stall_desc": None,
        },
        "forwarding": {
            "has_forwarded": False,
            "stage": None,
            "assembly": None,
            "forwarded_operand_count": 0,
            "forwarding_info": {
                "has_forwarded": False,
                "forwarded_from": [],
                "forwarded_to": [],
                "target_register": [],
                "forwarded_value": [],
            },
            "forwarding_desc": None,
        },
        "control_hazard": {
            "has_control_instruction": False,
            "has_flush": False,
            "stage": None,
            "assembly": None,
            "taken": None,
            "target_pc": None,
            "fallthrough_pc": None,
            "flushed_stages": [],
            "flush_reason": None,
            "redirect_pc": None,
        },
        "runtime_error": {
            "has_error": False,
            "code": None,
            "stage": None,
            "assembly": None,
            "message": None,
            "reason": None,
        },
    }


def _runtime_error_code(reason: str) -> str:
    if reason.startswith("명령어 주소"):
        return "INSTRUCTION_ALIGNMENT_ERROR"
    if "정렬" in reason:
        return "MEMORY_ALIGNMENT_ERROR"
    return "RUNTIME_ERROR"


def _record_runtime_error(state: dict, cycle_events: dict, stage: str, entry: Optional[dict], reason: str) -> None:
    state["status"] = "error"
    state["halt_requested"] = True
    code = _runtime_error_code(reason)
    message = f"[Error] {stage} stage runtime error"
    if entry is not None:
        message += f" at {entry['decoded']['assembly']}"
        entry["status"] = "error"
    message += f": {reason}"
    state["console_output"] += f"\n{message}"
    cycle_events["runtime_error"] = {
        "has_error": True,
        "code": code,
        "stage": stage,
        "assembly": entry["decoded"]["assembly"] if entry is not None else None,
        "message": reason,
        "reason": reason,
    }


def _stage_activity_snapshot(pipeline: dict) -> dict:
    return {
        "IF": _snapshot_stage("IF", pipeline["IF"]),
        "ID": _snapshot_stage("ID", pipeline["ID"]),
        "EX": _snapshot_stage("EX", pipeline["EX"]),
        "MEM": _snapshot_stage("MEM", pipeline["MEM"]),
        "WB": _snapshot_stage("WB", pipeline["WB"]),
    }


def _snapshot_stage(stage_name: str, entry: Optional[dict]) -> dict:
    result = _snapshot_stage_details(stage_name, entry)
    if entry is not None and entry["decoded"]["op"] != "nop":
        result["pc"] = _hex32(entry["pc"])
        result["raw_instruction"] = _hex32(entry["raw_instruction"])
    if entry is not None:
        result["flush_info"] = dict(entry["flush_info"])
    return result


def _snapshot_stage_details(stage_name: str, entry: Optional[dict]) -> dict:
    if entry is None:
        return {
            "assembly": "bubble",
            "status": "empty",
            "stage": stage_name,
        }

    decoded = entry["decoded"]
    if stage_name == "IF":
        return _if_stage_snapshot(entry["pc"], entry["raw_instruction"], decoded["assembly"], status=entry["status"], flushed=entry["flush_info"]["is_flushed"], reason=entry["flush_info"]["reason"])
    if stage_name == "ID":
        return _id_stage_snapshot(
            decoded,
            entry["rs1_val"],
            entry["rs2_val"],
            status=entry["status"],
            has_stall=entry.get("stall_desc") is not None,
            stall_reason=entry.get("stall_reason"),
            stall_desc=entry.get("stall_desc"),
        )
    if stage_name == "EX":
        if entry["alu"] is not None:
            alu = entry["alu"]
        else:
            alu = {
                "alu_op": decoded["op"],
                "operand1": entry["rs1_val"] if entry["rs1_val"] is not None else 0,
                "operand2": entry["rs2_val"] if entry["rs2_val"] is not None else 0,
                "alu_result": 0,
            }
        return _ex_stage_snapshot(
            decoded,
            alu,
            forwarding_info=entry.get("forwarding_info"),
            status=entry["status"],
            forwarding_desc=entry.get("forwarding_desc"),
        )
    if stage_name == "MEM":
        return _mem_stage_snapshot(decoded, entry["alu"]["alu_result"], entry["mem_read_data"], entry["mem_write_data"], status=entry["status"], flush_info=entry["flush_info"])
    if stage_name == "WB":
        return _wb_stage_snapshot(decoded, entry["write_val"], status=entry["status"], flush_info=entry["flush_info"])
    return {
        "assembly": decoded["assembly"],
        "status": entry["status"],
    }


def _handle_ecall(state: dict) -> None:
    a7 = state["regs"][17]
    if a7 == 10:
        state["status"] = "halted"
        state["halt_requested"] = True
    elif a7 == 1:
        state["console_output"] += str(_to_s32(state["regs"][10]))
    elif a7 == 4:
        address = state["regs"][10]
        state["console_output"] += read_string(state["dmem"], address)
    else:
        state["console_output"] += f"[ecall {a7} ignored]"


def _access_memory(state: dict, mem_entry: dict, cycle_events: dict) -> None:
    decoded = mem_entry["decoded"]
    alu_result = mem_entry["alu"]["alu_result"] & 0xFFFFFFFF
    try:
        if decoded["mem_read"]:
            if decoded["op"] == "lb":
                mem_entry["mem_read_data"] = load_byte(state["dmem"], alu_result, signed=True)
            elif decoded["op"] == "lh":
                mem_entry["mem_read_data"] = load_halfword(state["dmem"], alu_result, signed=True)
            elif decoded["op"] == "lbu":
                mem_entry["mem_read_data"] = load_byte(state["dmem"], alu_result, signed=False)
            elif decoded["op"] == "lhu":
                mem_entry["mem_read_data"] = load_halfword(state["dmem"], alu_result, signed=False)
            else:
                mem_entry["mem_read_data"] = load_word(state["dmem"], alu_result)
            mem_entry["write_val"] = mem_entry["mem_read_data"]
        elif decoded["mem_write"]:
            mem_entry["mem_write_data"] = mem_entry["rs2_val"]
            if decoded["op"] == "sb":
                store_byte(state["dmem"], alu_result, mem_entry["mem_write_data"])
            elif decoded["op"] == "sh":
                store_halfword(state["dmem"], alu_result, mem_entry["mem_write_data"])
            else:
                store_word(state["dmem"], alu_result, mem_entry["mem_write_data"])
    except ValueError as exc:
        _record_runtime_error(state, cycle_events, "MEM", mem_entry, str(exc))


def _execute_instruction(state: dict, ex_entry: dict, cycle_events: dict, *, pipelined: bool) -> bool:
    branch_flush = False
    decoded = ex_entry["decoded"]
    if decoded["op"] == "auipc":
        ex_entry["rs1_val"] = ex_entry["pc"]
    alu = execute(decoded, ex_entry["rs1_val"], ex_entry["rs2_val"])
    ex_entry["alu"] = alu
    if decoded["reg_write"] and not decoded["mem_read"]:
        ex_entry["write_val"] = alu["alu_result"]
    if decoded["branch"] and decoded["op"] in ("beq", "bne", "blt", "bge", "bltu", "bgeu"):
        target_pc = (ex_entry["pc"] + decoded["imm"]) & 0xFFFFFFFF
        fallthrough_pc = (ex_entry["pc"] + 4) & 0xFFFFFFFF
        taken = bool(alu["alu_result"])
        cycle_events["control_hazard"] = {
            "has_control_instruction": True,
            "has_flush": taken and pipelined,
            "stage": "EX",
            "assembly": decoded["assembly"],
            "taken": taken,
            "target_pc": _hex32(target_pc),
            "fallthrough_pc": _hex32(fallthrough_pc),
            "flushed_stages": ["IF", "ID"] if taken and pipelined else [],
            "flush_reason": "control_hazard_branch_taken" if taken and pipelined else None,
            "redirect_pc": _hex32(target_pc) if taken else None,
        }
        if alu["alu_result"]:
            state["pc"] = target_pc
            state["stats"]["control_hazards"] += int(pipelined)
            branch_flush = pipelined
    elif decoded["op"] == "jal":
        if decoded["rd"] != 0:
            ex_entry["write_val"] = (ex_entry["pc"] + 4) & 0xFFFFFFFF
        target_pc = (ex_entry["pc"] + decoded["imm"]) & 0xFFFFFFFF
        fallthrough_pc = (ex_entry["pc"] + 4) & 0xFFFFFFFF
        state["pc"] = target_pc
        cycle_events["control_hazard"] = {
            "has_control_instruction": True,
            "has_flush": pipelined,
            "stage": "EX",
            "assembly": decoded["assembly"],
            "taken": True,
            "target_pc": _hex32(target_pc),
            "fallthrough_pc": _hex32(fallthrough_pc),
            "flushed_stages": ["IF", "ID"] if pipelined else [],
            "flush_reason": "control_hazard_branch_taken" if pipelined else None,
            "redirect_pc": _hex32(target_pc),
        }
        state["stats"]["control_hazards"] += int(pipelined)
        branch_flush = pipelined
    elif decoded["op"] == "jalr":
        if decoded["rd"] != 0:
            ex_entry["write_val"] = (ex_entry["pc"] + 4) & 0xFFFFFFFF
        target_pc = (ex_entry["rs1_val"] + decoded["imm"]) & 0xFFFFFFFE
        fallthrough_pc = (ex_entry["pc"] + 4) & 0xFFFFFFFF
        state["pc"] = target_pc
        cycle_events["control_hazard"] = {
            "has_control_instruction": True,
            "has_flush": pipelined,
            "stage": "EX",
            "assembly": decoded["assembly"],
            "taken": True,
            "target_pc": _hex32(target_pc),
            "fallthrough_pc": _hex32(fallthrough_pc),
            "flushed_stages": ["IF", "ID"] if pipelined else [],
            "flush_reason": "control_hazard_branch_taken" if pipelined else None,
            "redirect_pc": _hex32(target_pc),
        }
        state["stats"]["control_hazards"] += int(pipelined)
        branch_flush = pipelined
    if cycle_events["control_hazard"]["taken"] and state["pc"] % 4:
        cycle_events["control_hazard"].update({
            "has_flush": False, "flushed_stages": [], "flush_reason": None, "redirect_pc": None,
        })
        _record_runtime_error(state, cycle_events, "EX", ex_entry,
                              f"명령어 주소가 4바이트 정렬되지 않음: {state['pc']:#010x}")
        return False
    return branch_flush


def _record_cycle(state: dict, stage_activity: dict, cycle_events: dict, *, single: bool = False) -> dict:
    snapshot = {
        "clock": state["stats"]["total_cycles"],
        "buffers": {stage: _buffer_snapshot(entry) for stage, entry in state["pipeline_regs"].items()},
        "stage_activity": stage_activity,
        "cycle_events": cycle_events,
        "global_result": _snapshot_global(state),
    }
    for stage in ("IF", "ID", "EX", "MEM", "WB"):
        snapshot[f"{stage.lower()}_stage"] = (
            stage_activity[stage] if single else _snapshot_stage(stage, state["pipeline_regs"][stage])
        )
    # Entries and hazard dictionaries continue to change on later clocks.
    snapshot = deepcopy(snapshot)
    state["history"].append(snapshot)
    state["stats"]["total_cycles"] += 1
    return snapshot
