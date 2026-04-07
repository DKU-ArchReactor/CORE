"""
시뮬레이터 모듈.

Non-Pipeline(단일 사이클) 시뮬레이션의 진입점.
core_single_tick()은 한 번 호출 시 명령어 하나를 IF→ID→EX→MEM→WB 순서로 완전 처리한다.
각 스테이지의 결과를 개별 dict로 추적하여 스냅샷에 포함한다.

Pipeline 확장 시 이 모듈에 core_pipeline_tick()을 추가하거나
별도 pipeline.py 모듈로 분리할 예정.
"""

import copy

from app.decoder import decode
from app.executor import execute
from app.memory import memory_access


def core_single_tick(user_id: str) -> dict | None:
    """
    Non-Pipeline 모드: 명령어 하나를 한 사이클에 완전히 처리한다.
    각 스테이지(IF/ID/EX/MEM/WB) 결과를 개별 dict로 반환한다.

    Args:
        user_id: 사용자 식별자 (GLOBAL_DICT 키)

    Returns:
        dict: 이번 사이클의 스냅샷 (5단계별 결과 포함)
        None: 프로그램 종료 시
    """
    from app.state import GLOBAL_DICT

    state = GLOBAL_DICT[user_id]

    # 프로그램 종료 체크
    if state["pc"] // 4 >= len(state["imem"]):
        state["status"] = "halted"
        return None

    state["status"] = "running"

    # ① IF: 명령어 가져오기
    pc_before = state["pc"]
    instr = state["imem"][state["pc"] // 4]
    stage_if = {
        "pc": pc_before,
        "instruction": instr,
    }

    # ② ID: 명령어 해석 + 레지스터 읽기
    decoded = decode(instr)
    rs1_val = state["regs"][decoded["rs1"]]
    rs2_val = state["regs"][decoded["rs2"]]
    stage_id = {
        "op": decoded["op"],
        "rd": decoded["rd"],
        "rs1": {"reg": decoded["rs1"], "value": rs1_val},
        "rs2": {"reg": decoded["rs2"], "value": rs2_val},
        "imm": decoded["imm"],
        "controls": {
            "reg_write": decoded["reg_write"],
            "mem_read": decoded["mem_read"],
            "mem_write": decoded["mem_write"],
            "branch": decoded["branch"],
        },
    }

    # ③ EX: ALU 연산
    alu_result = execute(decoded["op"], rs1_val, rs2_val, decoded["imm"])
    stage_ex = {
        "alu_result": alu_result,
        "alu_op": decoded["op"],
        "operand1": rs1_val,
        "operand2": rs2_val if decoded["op"] in (
            "add", "sub", "and", "or", "xor", "sll", "srl", "sra",
            "slt", "sltu", "beq", "bne", "blt", "bge", "bltu", "bgeu",
        ) else decoded["imm"],
    }

    # ④ MEM: 메모리 접근 (Load/Store일 때만)
    mem_data = memory_access(state["dmem"], decoded, alu_result, rs2_val)
    stage_mem = {
        "accessed": decoded["mem_read"] or decoded["mem_write"],
        "address": alu_result if (decoded["mem_read"] or decoded["mem_write"]) else None,
        "read_data": mem_data,
        "write_data": rs2_val if decoded["mem_write"] else None,
        "operation": "load" if decoded["mem_read"] else ("store" if decoded["mem_write"] else "none"),
    }

    # ⑤ WB: 레지스터에 결과 쓰기 (x0는 항상 0 유지)
    write_val = None
    if decoded["reg_write"] and decoded["rd"] != 0:
        write_val = mem_data if decoded["mem_read"] else alu_result
        state["regs"][decoded["rd"]] = write_val
    stage_wb = {
        "reg_write": decoded["reg_write"] and decoded["rd"] != 0,
        "rd": decoded["rd"],
        "write_data": write_val,
    }

    # PC 업데이트 (Branch / Jump 처리)
    if decoded["branch"] and decoded["op"] in ("beq", "bne", "blt", "bge", "bltu", "bgeu"):
        if alu_result:  # branch taken
            state["pc"] += decoded["imm"]
        else:
            state["pc"] += 4
    elif decoded["op"] == "jal":
        if decoded["reg_write"] and decoded["rd"] != 0:
            state["regs"][decoded["rd"]] = state["pc"] + 4  # 복귀 주소 저장
        state["pc"] += decoded["imm"]
    elif decoded["op"] == "jalr":
        if decoded["reg_write"] and decoded["rd"] != 0:
            state["regs"][decoded["rd"]] = state["pc"] + 4
        state["pc"] = (rs1_val + decoded["imm"]) & ~1
    else:
        state["pc"] += 4

    # 스냅샷 조립
    snapshot = {
        "cycle": state["stats"]["total_cycles"],
        "stages": {
            "IF": stage_if,
            "ID": stage_id,
            "EX": stage_ex,
            "MEM": stage_mem,
            "WB": stage_wb,
        },
        "registers": copy.copy(state["regs"]),
        "pc": state["pc"],
    }
    state["history"].append(snapshot)
    state["stats"]["total_cycles"] += 1
    state["stats"]["instructions_executed"] += 1

    return snapshot


def run_simulation(user_id: str, max_cycles: int = 50000) -> dict:
    """
    전체 시뮬레이션을 실행한다.
    Backend에서 POST /api/simulate 요청 시 호출되는 진입점.

    Args:
        user_id: 사용자 식별자
        max_cycles: 무한루프 방지용 최대 사이클 수

    Returns:
        dict: summary + history (프론트엔드 시각화용)
    """
    from app.state import GLOBAL_DICT

    state = GLOBAL_DICT[user_id]

    for _ in range(max_cycles):
        result = core_single_tick(user_id)
        if result is None:
            break

    return {
        "status": "success",
        "summary": copy.deepcopy(state["stats"]),
        "history": state["history"],
    }
