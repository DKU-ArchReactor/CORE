"""
state 모듈 테스트.
글로벌 딕셔너리의 생성/조회/삭제가 정상 동작하는지 검증한다.
"""

from app.state import create_state, get_state, delete_state, GLOBAL_DICT


def setup_function():
    """각 테스트 전에 GLOBAL_DICT를 초기화한다."""
    GLOBAL_DICT.clear()


def test_create_state():
    instructions = ["addi x1, x0, 10", "addi x2, x0, 20"]
    state = create_state("user_1", instructions)

    assert state["imem"] == instructions
    assert state["regs"] == [0] * 32
    assert state["pc"] == 0
    assert state["status"] == "ready"
    assert len(state["dmem"]) == 1024


def test_get_state():
    create_state("user_1", [])
    assert get_state("user_1") is not None
    assert get_state("nonexistent") is None


def test_delete_state():
    create_state("user_1", [])
    assert delete_state("user_1") is True
    assert get_state("user_1") is None
    assert delete_state("user_1") is False
