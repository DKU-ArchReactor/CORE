"""
시뮬레이터 모듈.

Non-Pipeline(단일 사이클) 시뮬레이션의 진입점.
core_single_tick()은 한 번 호출 시 명령어 하나를 IF→ID→EX→MEM→WB 순서로 완전 처리한다.

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
    정방향 실행 (IF → ID → EX → MEM → WB).

    Args:
        user_id: 사용자 식별자 (GLOBAL_DICT 키)

    Returns:
        dict: 이번 사이클의 스냅샷 (시각화용)
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
    instr = state["imem"][state["pc"] // 4]

    # ② ID: 명령어 해석 + 레지스터 읽기
    decoded = decode(instr)
    rs1_val = state["regs"][decoded["rs1"]]
    rs2_val = state["regs"][decoded["rs2"]]

    # ③ EX: ALU 연산
    alu_result = execute(decoded["op"], rs1_val, rs2_val, decoded["imm"])

    # ④ MEM: 메모리 접근 (Load/Store일 때만)
    mem_data = memory_access(state["dmem"], decoded, alu_result, rs2_val)

    # ⑤ WB: 레지스터에 결과 쓰기 (x0는 항상 0 유지)
    if decoded["reg_write"] and decoded["rd"] != 0:
        write_val = mem_data if decoded["mem_read"] else alu_result
        state["regs"][decoded["rd"]] = write_val

    # PC 업데이트
    state["pc"] += 4

    # 스냅샷 저장
    snapshot = {
        "cycle": state["stats"]["total_cycles"],
        "instr": instr,
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
