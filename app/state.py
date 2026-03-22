"""
글로벌 딕셔너리 (Single Source of Truth) 관리 모듈.

모든 사용자 상태(가상 CPU)를 GLOBAL_DICT에서 관리한다.
user_id 하나 = 가상 CPU 한 대.
Backend에서 직접 함수 호출로 접근하므로 직렬화 오버헤드가 없다.
"""

import copy

# 모든 사용자의 CPU 상태를 담는 단일 진실 소스
GLOBAL_DICT: dict = {}


def create_state(user_id: str, instructions: list[str]) -> dict:
    """
    새로운 사용자 상태(가상 CPU)를 초기화한다.

    Args:
        user_id: 사용자 고유 식별자
        instructions: 어셈블리 명령어 리스트 (imem에 로드)
    """
    state = {
        # 메모리 유닛
        "imem": instructions,           # Instruction Memory (Read Only)
        "dmem": [0] * 1024,             # Data Memory 4KB (Read/Write)

        # 실행 유닛
        "regs": [0] * 32,              # x0 ~ x31 레지스터
        "pc": 0,                        # Program Counter

        # 제어 및 통계
        "stats": {
            "total_cycles": 0,
            "instructions_executed": 0,
        },
        "status": "ready",             # ready | running | halted | error
        "history": [],                 # 사이클별 스냅샷 저장소
    }

    GLOBAL_DICT[user_id] = state
    return state


def get_state(user_id: str) -> dict:
    """사용자 상태를 조회한다."""
    return GLOBAL_DICT.get(user_id)


def delete_state(user_id: str) -> bool:
    """사용자 상태를 삭제한다 (세션 종료)."""
    if user_id in GLOBAL_DICT:
        del GLOBAL_DICT[user_id]
        return True
    return False
