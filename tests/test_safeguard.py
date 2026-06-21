"""
Simulator safeguard tests.
"""

from app.state import create_state, delete_state, GLOBAL_DICT
from app.simulator import run_simulation


def setup_function():
    GLOBAL_DICT.clear()


def _make_infinite_loop_program() -> bytes:
    # 0: nop
    # 4: jal x0, -4
    nop = 0x00000013
    jal = 0xFFDFF06F
    return nop.to_bytes(4, "little") + jal.to_bytes(4, "little")


def test_clock_safeguard_stops_after_max_clocks():
    elf_bytes = _make_infinite_loop_program()
    state = create_state("user_loop", elf_bytes, mode="single")
    state["pc"] = 4
    result = run_simulation("user_loop", max_cycles=2000)

    assert result["status"] == "error"
    assert state["stats"]["total_cycles"] == 2000
    assert "Execution clock limit exceeded" in state["console_output"]
    assert len(result["history"]) == 2000
