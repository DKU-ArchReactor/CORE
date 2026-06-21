"""
state 모듈 테스트.
dict 기반 메모리 및 상태 빌드가 올바르게 동작하는지 검증한다.
"""

from app.state import create_state, get_state, delete_state, GLOBAL_DICT


def setup_function():
    GLOBAL_DICT.clear()


def test_create_state_single_mode_initializes_pipeline_buffers():
    state = create_state("user1", b"\x00\x00\x00\x00", mode="single")
    assert state["mode"] == "single"
    assert isinstance(state["pipeline_regs"], dict)
    assert set(state["pipeline_regs"].keys()) == {"IF", "ID", "EX", "MEM", "WB"}
    assert all(value is None for value in state["pipeline_regs"].values())


def test_create_state_pipeline_mode_initializes_buffers():
    state = create_state("user2", b"\x00\x00\x00\x00", mode="pipeline")
    assert state["mode"] == "pipeline"
    assert isinstance(state["pipeline_regs"], dict)
    assert set(state["pipeline_regs"].keys()) == {"IF", "ID", "EX", "MEM", "WB"}
    assert all(value is None for value in state["pipeline_regs"].values())


def test_absolute_address_load_store():
    state = create_state("user3", b"\x00\x00\x00\x00", mode="single")
    state["dmem"][0x80001000] = 0x12345678
    assert state["dmem"][0x80001000] == 0x12345678


def test_get_and_delete_state():
    create_state("user4", b"\x00\x00\x00\x00", mode="single")
    assert get_state("user4") is not None
    assert delete_state("user4") is True
    assert get_state("user4") is None
