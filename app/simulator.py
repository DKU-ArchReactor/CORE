"""
시뮬레이터 모듈.

Single-cycle 및 5-stage pipeline 모드를 지원하며,
각 사이클을 6-part 히스토리 객체로 기록한다.
"""

from __future__ import annotations

from typing import Dict, Optional

from app.decoder import decode
from app.executor import execute
from app.memory import (
    load_byte,
    load_halfword,
    load_word,
    read_string,
    store_byte,
    store_halfword,
    store_word,
)
from app.state import GLOBAL_DICT, register_name

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
        "will_write_reg": decoded["reg_write"] and decoded["rd"] != 0,
        "destination_register": register_name(decoded["rd"]),
        "final_write_data": _hex32(write_val) if write_val is not None else None,
    }


def _make_pipeline_entry(pc: int, raw_word: int) -> dict:
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


def _is_writeback_candidate(entry: Optional[dict]) -> bool:
    return bool(entry and entry["decoded"]["reg_write"] and entry["decoded"]["rd"] != 0)


def _detect_pipeline_stall(state: dict, pipeline: dict) -> Optional[dict]:
    if state["mode"] != "pipeline":
        return None

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
        for stage_name in ("EX", "MEM", "WB"):
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


def _has_active_pipeline(state: dict) -> bool:
    return any(state["pipeline_regs"][stage] is not None for stage in ("IF", "ID", "EX", "MEM", "WB"))


def _fetch_pipeline_entry(state: dict) -> Optional[dict]:
    if state["pc"] not in state["imem"]:
        return None
    raw_word = state["imem"][state["pc"]]
    entry = _make_pipeline_entry(state["pc"], raw_word)
    state["pc"] += 4
    return entry


def core_single_tick(user_id: str) -> Optional[dict]:
    state = GLOBAL_DICT[user_id]
    if state["status"] == "error":
        return None

    if state["stats"]["total_cycles"] >= MAX_CYCLES:
        state["status"] = "error"
        state["console_output"] += "\n[Error] Execution clock limit exceeded (Max: 2000 clocks). Possible infinite loop detected."
        return None

    if state["status"] == "halted" and not _has_active_pipeline(state):
        return None

    pipeline = state["pipeline_regs"]
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
        state["stats"]["instructions_executed"] += 1
        if state["mode"] == "single" and decoded["reg_write"] and decoded["rd"] != 0:
            state["recent_rds"].append(decoded["rd"])
            if len(state["recent_rds"]) > 2:
                state["recent_rds"] = state["recent_rds"][-2:]

    mem_entry = pipeline["MEM"]
    if state["status"] != "error" and mem_entry is not None and mem_entry["decoded"]["op"] != "nop":
        decoded = mem_entry["decoded"]
        alu_result = mem_entry["alu"]["alu_result"]
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

    id_entry = pipeline["ID"]
    if state["status"] != "error" and id_entry is not None and id_entry["decoded"]["op"] != "nop":
        decoded = id_entry["decoded"]
        id_entry["rs1_val"] = state["regs"][decoded["rs1"]]
        id_entry["rs2_val"] = state["regs"][decoded["rs2"]]

    ex_entry = pipeline["EX"]
    if state["status"] != "error" and ex_entry is not None and ex_entry["decoded"]["op"] != "nop":
        if state["forwarding_enabled"]:
            _compute_forwarding(state, ex_entry, mem_entry, wb_entry)
        decoded = ex_entry["decoded"]
        if decoded["op"] == "auipc":
            ex_entry["rs1_val"] = ex_entry["pc"]
        alu = execute(decoded, ex_entry["rs1_val"], ex_entry["rs2_val"])
        ex_entry["alu"] = alu
        if decoded["reg_write"] and not decoded["mem_read"]:
            ex_entry["write_val"] = alu["alu_result"]
        if decoded["branch"] and decoded["op"] in ("beq", "bne", "blt", "bge", "bltu", "bgeu"):
            target_pc = ex_entry["pc"] + decoded["imm"]
            fallthrough_pc = ex_entry["pc"] + 4
            taken = bool(alu["alu_result"])
            cycle_events["control_hazard"] = {
                "has_control_instruction": True,
                "has_flush": taken,
                "stage": "EX",
                "assembly": decoded["assembly"],
                "taken": taken,
                "target_pc": _hex32(target_pc),
                "fallthrough_pc": _hex32(fallthrough_pc),
                "flushed_stages": ["IF", "ID"] if taken else [],
                "flush_reason": "control_hazard_branch_taken" if taken else None,
                "redirect_pc": _hex32(target_pc) if taken else None,
            }
            if alu["alu_result"]:
                state["pc"] = target_pc
                redirect_pc = state["pc"]
                state["stats"]["control_hazards"] += 1
                branch_flush = True
                flush_reason = "control_hazard_branch_taken"
        elif decoded["op"] == "jal":
            if decoded["rd"] != 0:
                ex_entry["write_val"] = ex_entry["pc"] + 4
            target_pc = ex_entry["pc"] + decoded["imm"]
            fallthrough_pc = ex_entry["pc"] + 4
            state["pc"] = target_pc
            redirect_pc = state["pc"]
            cycle_events["control_hazard"] = {
                "has_control_instruction": True,
                "has_flush": True,
                "stage": "EX",
                "assembly": decoded["assembly"],
                "taken": True,
                "target_pc": _hex32(target_pc),
                "fallthrough_pc": _hex32(fallthrough_pc),
                "flushed_stages": ["IF", "ID"],
                "flush_reason": "control_hazard_branch_taken",
                "redirect_pc": _hex32(target_pc),
            }
            state["stats"]["control_hazards"] += 1
            branch_flush = True
            flush_reason = "control_hazard_branch_taken"
        elif decoded["op"] == "jalr":
            if decoded["rd"] != 0:
                ex_entry["write_val"] = ex_entry["pc"] + 4
            target_pc = (ex_entry["rs1_val"] + decoded["imm"]) & ~1
            fallthrough_pc = ex_entry["pc"] + 4
            state["pc"] = target_pc
            redirect_pc = state["pc"]
            cycle_events["control_hazard"] = {
                "has_control_instruction": True,
                "has_flush": True,
                "stage": "EX",
                "assembly": decoded["assembly"],
                "taken": True,
                "target_pc": _hex32(target_pc),
                "fallthrough_pc": _hex32(fallthrough_pc),
                "flushed_stages": ["IF", "ID"],
                "flush_reason": "control_hazard_branch_taken",
                "redirect_pc": _hex32(target_pc),
            }
            state["stats"]["control_hazards"] += 1
            branch_flush = True
            flush_reason = "control_hazard_branch_taken"

    stall_info = None if state["status"] == "error" else _detect_pipeline_stall(state, pipeline)
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
    stage_activity = _stage_activity_snapshot(pipeline)

    fetch_entry = None
    if state["status"] == "error":
        fetch_entry = None
    elif not state["halt_requested"] and state["mode"] == "pipeline":
        if branch_flush:
            fetch_entry = None
        elif stall_info:
            fetch_entry = pipeline["IF"]
        else:
            fetch_entry = _fetch_pipeline_entry(state)
    elif not state["halt_requested"] and state["mode"] == "single":
        if not _has_active_pipeline(state):
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

    virtual_hazard_alert = None
    if state["mode"] == "single":
        id_snapshot_entry = state["pipeline_regs"]["ID"]
        if id_snapshot_entry is not None and id_snapshot_entry["decoded"]["op"] != "nop":
            rs1 = id_snapshot_entry["decoded"]["rs1"]
            rs2 = id_snapshot_entry["decoded"]["rs2"]
            if rs1 in state["recent_rds"] or rs2 in state["recent_rds"]:
                virtual_hazard_alert = "💡 파이프라인 모드 구동 예습: 만약 파이프라인 모드였다면, 앞선 명령어와의 데이터 의존성 때문에 여기서 데이터 하자드(충돌)가 발생했을 구간입니다."

    if not _has_active_pipeline(state) and state["pc"] not in state["imem"] and not state["halt_requested"]:
        state["status"] = "halted"

    snapshot = {
        "clock": state["stats"]["total_cycles"],
        "buffers": {
            "IF": _buffer_snapshot(state["pipeline_regs"]["IF"]),
            "ID": _buffer_snapshot(state["pipeline_regs"]["ID"]),
            "EX": _buffer_snapshot(state["pipeline_regs"]["EX"]),
            "MEM": _buffer_snapshot(state["pipeline_regs"]["MEM"]),
            "WB": _buffer_snapshot(state["pipeline_regs"]["WB"]),
        },
        "if_stage": _snapshot_stage("IF", state["pipeline_regs"]["IF"]),
        "id_stage": _snapshot_stage("ID", state["pipeline_regs"]["ID"]),
        "ex_stage": _snapshot_stage("EX", state["pipeline_regs"]["EX"]),
        "mem_stage": _snapshot_stage("MEM", state["pipeline_regs"]["MEM"]),
        "wb_stage": _snapshot_stage("WB", state["pipeline_regs"]["WB"]),
        "stage_activity": stage_activity,
        "cycle_events": cycle_events,
        "global_result": _snapshot_global(state),
    }
    if virtual_hazard_alert is not None:
        snapshot["virtual_hazard_alert"] = virtual_hazard_alert

    state["history"].append(snapshot)
    state["stats"]["total_cycles"] += 1

    if state["status"] == "halted" and not _has_active_pipeline(state):
        return snapshot

    return snapshot


def run_simulation(user_id: str, max_cycles: int = MAX_CYCLES) -> dict:
    state = GLOBAL_DICT[user_id]
    while state["status"] not in ("halted", "error"):
        if state["stats"]["total_cycles"] >= max_cycles:
            state["status"] = "error"
            state["console_output"] += "\n[Error] Execution clock limit exceeded (Max: 2000 clocks). Possible infinite loop detected."
            break
        result = core_single_tick(user_id)
        if result is None:
            break

    return {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "simulator": {
            "mode": state["mode"],
            "max_cycles": max_cycles,
            "pipeline_model": "5-stage-in-order",
        },
        "program": {
            "entry_point": _hex32(state["entry_point"]),
            "instruction_words": len(state["imem"]),
            "data_words": len(state["dmem"]),
        },
        "status": state["status"],
        "summary": {
            **state["stats"],
            "executed_cycles": len(state["history"]),
        },
        "history": state["history"],
        "console_output": state["console_output"],
    }
