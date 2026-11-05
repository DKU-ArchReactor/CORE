"""Public simulation API and execution-mode dispatch."""

from __future__ import annotations

from typing import Optional

from app import pipeline_engine, single_cycle_engine
from app.engine_common import HISTORY_SCHEMA_VERSION, MAX_CYCLES, _hex32
from app.state import GLOBAL_DICT


def _clock_limit(state: dict, max_cycles: int) -> None:
    state["status"] = "error"
    state["halt_requested"] = True
    state["console_output"] += (
        f"\n[Error] Execution clock limit exceeded (Max: {max_cycles} clocks). Possible infinite loop detected."
    )


def core_single_tick(user_id: str) -> Optional[dict]:
    """Advance one clock of the selected engine (legacy API name)."""
    state = GLOBAL_DICT[user_id]
    if state["status"] in ("halted", "error"):
        return None
    if state["stats"]["total_cycles"] >= MAX_CYCLES:
        _clock_limit(state, MAX_CYCLES)
        return None
    if state["mode"] == "single":
        return single_cycle_engine.tick(state)
    if state["mode"] == "pipeline":
        return pipeline_engine.tick(state)
    raise ValueError(f"Unsupported simulation mode: {state['mode']}")


def run_simulation(user_id: str, max_cycles: int = MAX_CYCLES) -> dict:
    if isinstance(max_cycles, bool) or not isinstance(max_cycles, int) or not 1 <= max_cycles <= MAX_CYCLES:
        raise ValueError(f"max_cycles must be an integer between 1 and {MAX_CYCLES}")
    state = GLOBAL_DICT[user_id]
    while state["status"] not in ("halted", "error"):
        if state["stats"]["total_cycles"] >= max_cycles:
            _clock_limit(state, max_cycles)
            break
        result = core_single_tick(user_id)
        if result is None:
            break

    return {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "simulator": {
            "mode": state["mode"],
            "max_cycles": max_cycles,
            "pipeline_model": "single-cycle" if state["mode"] == "single" else "5-stage-in-order",
        },
        "program": {
            **state["program_metadata"],
            "entry_point": _hex32(state["entry_point"]),
            "instruction_words": len(state["imem"]),
            "data_words": len(state["initial_state"]["memory_snapshot"]),
        },
        "status": state["status"],
        "initial_state": state["initial_state"],
        "summary": {
            **state["stats"],
            "executed_cycles": len(state["history"]),
        },
        "history": state["history"],
        "console_output": state["console_output"],
    }
