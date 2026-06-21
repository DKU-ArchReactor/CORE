"""
시뮬레이터 모듈.

Single-cycle 및 5-stage pipeline 모드를 지원하며,
각 사이클을 6-part 히스토리 객체로 기록한다.
"""

from __future__ import annotations

from typing import Dict, Optional

from app.decoder import decode
from app.executor import execute
from app.memory import load_word, store_word, read_string
from app.state import GLOBAL_DICT, register_name

MAX_CYCLES = 2000


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


def _if_stage_snapshot(state: dict, raw_word: int, assembly: str, status: str = "normal", flushed: bool = False, reason: Optional[str] = None) -> dict:
    return {
        "pc": _hex32(state["pc"]),
        "raw_instruction": _hex32(raw_word),
        "assembly": assembly,
        "status": status,
        "flush_info": {
            "is_flushed": flushed,
            "reason": reason,
        },
    }


def _id_stage_snapshot(decoded: dict, rs1_val: Optional[int], rs2_val: Optional[int], status: str = "normal", has_stall: bool = False, stall_reason: Optional[str] = None) -> dict:
    rs1_hex = _hex32(rs1_val) if rs1_val is not None else "0x00000000"
    rs2_hex = _hex32(rs2_val) if rs2_val is not None else "0x00000000"
    return {
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


def _ex_stage_snapshot(decoded: dict, alu: dict, forwarding_info: Optional[dict] = None, status: str = "normal") -> dict:
    status = status if status != "normal" else ("forwarding_active" if forwarding_info and forwarding_info.get("has_forwarded") else "normal")
    return {
        "assembly": decoded["assembly"],
        "status": status,
        "alu_operation": alu["alu_op"],
        "operand_1": _hex32(alu["operand1"]),
        "operand_2": _hex32(alu["operand2"]),
        "alu_result": _hex32(alu["alu_result"]),
        "forwarding_info": forwarding_info or {
            "has_forwarded": False,
            "forwarded_from": None,
            "forwarded_to": None,
            "target_register": None,
        },
        "flush_info": {
            "is_flushed": False,
            "reason": None,
        },
    }


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
    }


def _buffer_snapshot(entry: Optional[dict]) -> Optional[dict]:
    if entry is None:
        return None
    return {
        "pc": _hex32(entry["pc"]),
        "raw_instruction": _hex32(entry["raw_instruction"]),
        "assembly": entry["decoded"]["assembly"],
        "status": entry["status"],
        "flush_info": entry["flush_info"],
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
        return _if_stage_snapshot(entry, entry["raw_instruction"], decoded["assembly"], status=entry["status"], flushed=entry["flush_info"]["is_flushed"], reason=entry["flush_info"]["reason"])
    if stage_name == "ID":
        return _id_stage_snapshot(decoded, entry["rs1_val"], entry["rs2_val"], status=entry["status"])
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
        return _ex_stage_snapshot(decoded, alu, status=entry["status"])
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
    elif a7 in (1, 4):
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

    # Commit WB stage.
    wb_entry = pipeline["WB"]
    if wb_entry is not None:
        decoded = wb_entry["decoded"]
        if decoded["reg_write"] and decoded["rd"] != 0 and wb_entry["write_val"] is not None:
            state["regs"][decoded["rd"]] = wb_entry["write_val"]
        if decoded["op"] == "ecall":
            _handle_ecall(state)
        state["stats"]["instructions_executed"] += 1

    # Execute MEM stage.
    mem_entry = pipeline["MEM"]
    if mem_entry is not None:
        decoded = mem_entry["decoded"]
        alu_result = mem_entry["alu"]["alu_result"]
        if decoded["mem_read"]:
            mem_entry["mem_read_data"] = load_word(state["dmem"], alu_result)
            mem_entry["write_val"] = mem_entry["mem_read_data"]
        elif decoded["mem_write"]:
            mem_entry["mem_write_data"] = mem_entry["rs2_val"]
            store_word(state["dmem"], alu_result, mem_entry["mem_write_data"])

    # Execute EX stage.
    ex_entry = pipeline["EX"]
    if ex_entry is not None:
        decoded = ex_entry["decoded"]
        alu = execute(decoded, ex_entry["rs1_val"], ex_entry["rs2_val"])
        ex_entry["alu"] = alu
        if decoded["reg_write"] and not decoded["mem_read"]:
            ex_entry["write_val"] = alu["alu_result"]
        if decoded["branch"] and decoded["op"] in ("beq", "bne", "blt", "bge", "bltu", "bgeu"):
            if alu["alu_result"]:
                state["pc"] = ex_entry["pc"] + decoded["imm"]
                state["stats"]["control_hazards"] += 1
                branch_flush = True
                flush_reason = "control_hazard_branch_taken"
        elif decoded["op"] == "jal":
            if decoded["rd"] != 0:
                ex_entry["write_val"] = ex_entry["pc"] + 4
            state["pc"] = ex_entry["pc"] + decoded["imm"]
            state["stats"]["control_hazards"] += 1
            branch_flush = True
            flush_reason = "control_hazard_branch_taken"
        elif decoded["op"] == "jalr":
            if decoded["rd"] != 0:
                ex_entry["write_val"] = ex_entry["pc"] + 4
            state["pc"] = (ex_entry["rs1_val"] + decoded["imm"]) & ~1
            state["stats"]["control_hazards"] += 1
            branch_flush = True
            flush_reason = "control_hazard_branch_taken"

    # Execute ID stage.
    id_entry = pipeline["ID"]
    if id_entry is not None:
        decoded = id_entry["decoded"]
        id_entry["rs1_val"] = state["regs"][decoded["rs1"]]
        id_entry["rs2_val"] = state["regs"][decoded["rs2"]]

    # Fetch stage: single mode fetch only when pipeline is empty, pipeline mode fetch whenever IF is empty.
    fetch_entry = None
    if not state["halt_requested"]:
        if state["mode"] == "single":
            if not _has_active_pipeline(state):
                fetch_entry = _fetch_pipeline_entry(state)
        else:
            if pipeline["IF"] is None:
                fetch_entry = _fetch_pipeline_entry(state)

    if branch_flush:
        if pipeline["IF"] is not None:
            pipeline["IF"]["status"] = "flushed"
            pipeline["IF"]["flush_info"] = {"is_flushed": True, "reason": flush_reason}
        if pipeline["ID"] is not None:
            pipeline["ID"]["status"] = "flushed"
            pipeline["ID"]["flush_info"] = {"is_flushed": True, "reason": flush_reason}
        fetch_entry = None

    # Advance pipeline registers.
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
        "global_result": _snapshot_global(state),
    }

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
        "status": state["status"],
        "summary": {
            **state["stats"],
            "executed_cycles": len(state["history"]),
        },
        "history": state["history"],
        "console_output": state["console_output"],
    }
