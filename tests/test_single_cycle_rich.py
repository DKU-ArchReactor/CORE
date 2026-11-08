"""Tests for enriched single-cycle datapath and authoritative memory_layout metadata."""

import io
from pathlib import Path
from app.state import create_state, delete_state
from app.simulator import run_simulation

SAMPLE_ELF = (Path(__file__).parent / "program2.elf").read_bytes()


def test_memory_layout_metadata():
    user_id = "test_memory_layout_user"
    try:
        create_state(user_id, SAMPLE_ELF, mode="single")
        result = run_simulation(user_id, max_cycles=100)
        assert result["status"] == "halted"
        
        program = result["program"]
        assert "memory_layout" in program
        layout = program["memory_layout"]
        
        # Check all 6 virtual memory segments
        assert "stack" in layout
        assert layout["stack"]["base"] == "0x7FFFEFFC"
        assert layout["stack"]["limit"] == "0x10008000"
        
        assert "heap" in layout
        assert layout["heap"]["base"] == "0x10004000"
        assert layout["heap"]["limit"] == "0x10008000"
        
        assert "bss" in layout
        assert "data" in layout
        assert "code" in layout
        assert "reserved" in layout
        assert layout["reserved"]["start"] == "0x00000000"
        assert layout["reserved"]["end_exclusive"] == "0x00010000"
        
        # Check code separation
        code = layout["code"]
        assert "runtime_startup" in code
        assert "user_program" in code
        assert int(code["start"], 16) >= 0x00010000
        assert int(code["end_exclusive"], 16) > int(code["start"], 16)
        
        # Check authoritative boundary dividers
        assert "boundary_dividers" in layout
        assert len(layout["boundary_dividers"]) == 6
        assert layout["boundary_dividers"][0] == "0x10008000"
        assert layout["boundary_dividers"][1] == "0x10004000"
        assert layout["boundary_dividers"][4] == "0x00010000"
        assert layout["boundary_dividers"][5] == "0x00000000"
    finally:
        delete_state(user_id)


def test_single_cycle_rich_datapath():
    user_id = "test_single_cycle_rich_user"
    try:
        create_state(user_id, SAMPLE_ELF, mode="single")
        result = run_simulation(user_id, max_cycles=100)
        assert result["status"] == "halted"
        assert len(result["history"]) > 0
        
        first_cycle = result["history"][0]
        assert "datapath" in first_cycle
        dp = first_cycle["datapath"]
        
        assert "pc" in dp
        assert "next_pc" in dp
        assert "control_signals" in dp
        cs = dp["control_signals"]
        assert "reg_write" in cs
        assert "alu_src" in cs
        assert "alu_op" in cs
        assert "mem_read" in cs
        assert "mem_write" in cs
        assert "mem_to_reg" in cs
        assert "branch" in cs
        assert "jump" in cs
        assert "pc_src" in cs
        
        assert "registers" in dp
        assert "rs1" in dp["registers"]
        assert "rs2" in dp["registers"]
        assert "rd" in dp["registers"]
        
        assert "alu" in dp
        assert "input_1" in dp["alu"]
        assert "input_2" in dp["alu"]
        assert "result" in dp["alu"]
        assert "zero" in dp["alu"]
        
        assert "data_memory" in dp
        assert "global_result" in first_cycle
        assert "active_stack_pointer" in first_cycle["global_result"]
    finally:
        delete_state(user_id)
