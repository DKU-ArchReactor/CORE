# Simulation History Schema

This document defines the current JSON result contract returned by `run_simulation()`.

Each cycle describes the work performed by the selected execution engine and the resulting architectural state.

## Top-Level Result

```json
{
  "schema_version": "1.0",
  "simulator": {},
  "program": {},
  "status": "halted",
  "summary": {},
  "history": [],
  "console_output": ""
}
```

Fields:

- `schema_version`: schema contract version for frontend/backend compatibility
- `simulator`: simulator configuration metadata
- `program`: loaded program metadata
- `initial_state`: architectural state before the first clock (same shape as `global_result`)
- `status`: `ready`, `halted`, or `error`
- `summary`: accumulated execution counters
- `history`: ordered list of per-cycle snapshots
- `console_output`: text produced by intercepted `ecall`

## Simulator Metadata

```json
{
  "mode": "pipeline",
  "max_cycles": 2000,
  "pipeline_model": "5-stage-in-order"
}
```

For `mode = "single"`, `pipeline_model` is `"single-cycle"`. For
`mode = "pipeline"`, it is `"5-stage-in-order"`.

Pipeline IF runs on the first clock; no empty setup clock is included.
N independent instructions with no redirects or stalls take N+4 clocks.

## Program Metadata

```json
{
  "entry_point": "0x00010128",
  "instruction_words": 97,
  "data_words": 28
}
```

## Summary

Program metadata additionally includes `fingerprint` (SHA-256 of input ELF/raw
bytes), `instructions` (actual PC, raw word, decoded assembly),
`memory_regions` (ELF section name, start, exclusive end, kind), and
`initial_stack_pointer`. `data_words` counts initially loaded data words,
not words created by stores during execution. Raw programs have no ELF regions.

```json
{
  "total_cycles": 134,
  "instructions_executed": 97,
  "data_hazards": 9,
  "control_hazards": 8,
  "stalls": 9,
  "forwards": 44,
  "executed_cycles": 134
}
```

Counter meanings:

- `total_cycles`: simulator clock count
- `instructions_executed`: successfully completed instructions (at WB in pipeline mode); faulting instructions do not retire
- `data_hazards`: data hazards that caused stalls
- `control_hazards`: taken branch/jump redirects that flushed younger instructions
- `stalls`: inserted stall bubbles
- `forwards`: forwarded operand count, not cycle count
- `executed_cycles`: length of `history`

In single mode, each successfully completed instruction takes one clock, and
`data_hazards`, `control_hazards`, `stalls`, and `forwards` remain zero. A faulting
instruction contributes a clock/history entry but does not increment
`instructions_executed`. Taken single-mode branches still emit control-flow
events; they do not cause pipeline flushes or bubbles.

## Cycle Snapshot

Each item in `history` has:

```json
{
  "clock": 0,
  "buffers": {},
  "if_stage": {},
  "id_stage": {},
  "ex_stage": {},
  "mem_stage": {},
  "wb_stage": {},
  "stage_activity": {},
  "cycle_events": {},
  "global_result": {}
}
```

In pipeline mode there are two stage views:

- `stage_activity`: what each stage did during this clock before pipeline registers advanced
- `if_stage` through `wb_stage`: compatibility view of stage contents after pipeline registers advanced

Prefer `stage_activity` and `cycle_events` for teaching UI.

In single mode, all five `stage_activity` entries describe the **same**
instruction completed during that clock. `if_stage` through `wb_stage` expose
the corresponding activity, and all `buffers` entries are `null`. A fault
leaves stages after the fault empty. `global_result` includes the completed
instruction's register/memory writes in that same history entry.

Do not select a completed instruction by searching `buffers.WB`: in pipeline
mode that buffer contains next-clock work, and in single mode it is empty.
Single-mode consumers should step through `history` in order and use
`if_stage.pc` to identify the dynamic instruction. Static assembly line counts
cannot represent repeated loop iterations, skipped branches, or function calls.

History snapshots are detached from live CPU/pipeline dictionaries; advancing
the simulator does not modify earlier snapshots. Calling `core_single_tick()`
after halt/error returns `null` (Python `None`) without further execution.

## Buffers

`buffers` describes pipeline register state after the clock edge:

```json
{
  "IF": null,
  "ID": {
    "pc": "0x00010144",
    "raw_instruction": "0x03200793",
    "assembly": "addi a5, zero, 50",
    "status": "normal",
    "flush_info": {
      "is_flushed": false,
      "reason": null
    }
  }
}
```

`null` means the pipeline register is empty.

Possible `status` values include:

- `normal`
- `empty`
- `stalled`
- `flushed`
- `forwarding_active`
- `error`

## Stage Activity

`stage_activity` has one entry per stage:

```json
{
  "IF": {},
  "ID": {},
  "EX": {},
  "MEM": {},
  "WB": {}
}
```

Use this view to answer: “What did this stage do in this clock?”

ID activity includes decoded fields and hazard detection:

```json
{
  "assembly": "addi a0, a5, 0",
  "status": "stalled",
  "decoded_fields": {
    "op": "addi",
    "rd": "x10",
    "rs1": {
      "name": "a5",
      "num": 15,
      "current_value": "0x00010000"
    },
    "rs2": {
      "name": "zero",
      "num": 0,
      "current_value": "0x00000000"
    },
    "imm": 0
  },
  "hazard_detect": {
    "has_stall": true,
    "stall_reason": "load_use"
  },
  "stall_desc": "..."
}
```

EX activity includes ALU operands, results, and forwarding:

```json
{
  "assembly": "sw ra, 60(sp)",
  "status": "forwarding_active",
  "alu_operation": "sw",
  "operand_1": "0x7FFFEFBC",
  "operand_2": "0x00000000",
  "alu_result": "0x7FFFEFF8",
  "forwarding_info": {
    "has_forwarded": true,
    "forwarded_from": ["EX/MEM"],
    "forwarded_to": ["rs1"],
    "target_register": ["sp"],
    "forwarded_value": ["0x7FFFEFBC"]
  },
  "forwarding_desc": "..."
}
```

MEM activity includes memory operation details:

```json
{
  "assembly": "lw a5, -20(s0)",
  "status": "normal",
  "memory_operation": "load",
  "target_address": "0x7FFFEFAC",
  "read_data": "0x0000003C",
  "write_data": null
}
```

WB activity includes register writeback intent:

```json
{
  "assembly": "addi a5, zero, 50",
  "status": "normal",
  "will_write_reg": true,
  "destination_register": "a5",
  "final_write_data": "0x00000032"
}
```

## Cycle Events

`cycle_events` is the primary teaching surface for hazards and exceptions.

```json
{
  "stall": {},
  "forwarding": {},
  "control_hazard": {},
  "runtime_error": {}
}
```

### Stall

```json
{
  "has_stall": true,
  "stage": "ID",
  "assembly": "addi a0, a5, 0",
  "stall_reason": "load_use",
  "stall_desc": "..."
}
```

When forwarding is enabled, current stall reason:

- `load_use`: a load in EX is producing a value needed by the instruction in ID

When forwarding is disabled:

- `strict_dependency`: ID depends on a writeback candidate still in EX/MEM; WB writes before ID reads

### Forwarding

```json
{
  "has_forwarded": true,
  "stage": "EX",
  "assembly": "addi x6, x5, 1",
  "forwarded_operand_count": 1,
  "forwarding_info": {
    "has_forwarded": true,
    "forwarded_from": ["EX/MEM"],
    "forwarded_to": ["rs1"],
    "target_register": ["t0"],
    "forwarded_value": ["0x00000001"]
  },
  "forwarding_desc": "..."
}
```

`forwarded_operand_count` maps directly to `summary.forwards`.

### Control Hazard

Taken branch:

```json
{
  "has_control_instruction": true,
  "has_flush": true,
  "stage": "EX",
  "assembly": "beq zero, zero, 8",
  "taken": true,
  "target_pc": "0x00000008",
  "fallthrough_pc": "0x00000004",
  "flushed_stages": ["IF", "ID"],
  "flush_reason": "control_hazard_branch_taken",
  "redirect_pc": "0x00000008"
}
```

Not-taken branch:

```json
{
  "has_control_instruction": true,
  "has_flush": false,
  "stage": "EX",
  "assembly": "bne zero, zero, 8",
  "taken": false,
  "target_pc": "0x00000008",
  "fallthrough_pc": "0x00000004",
  "flushed_stages": [],
  "flush_reason": null,
  "redirect_pc": null
}
```

### Runtime Error

```json
{
  "has_error": true,
  "code": "MEMORY_ALIGNMENT_ERROR",
  "stage": "MEM",
  "assembly": "lw t0, 2(zero)",
  "message": "메모리 주소가 4바이트 워드 정렬되지 않음: 0x00000002",
  "reason": "메모리 주소가 4바이트 워드 정렬되지 않음: 0x00000002"
}
```

Runtime errors stop simulation with `status = "error"`.

Current runtime error codes:

- `MEMORY_ALIGNMENT_ERROR`
- `RUNTIME_ERROR`
- `INSTRUCTION_ALIGNMENT_ERROR`

Errors stop execution immediately. This educational model does not drain older
in-flight instructions after an EX-stage error, and does not model precise
architectural exception delivery.

## Global Result

`global_result` is an architectural state snapshot after the clock:

```json
{
  "current_pc": "0x00010144",
  "registers": {
    "x0": "0x00000000"
  },
  "memory_snapshot": {
    "0x00010218": "0x61766441"
  },
  "console_output": "",
  "metrics": {
    "accumulated_instructions": 0,
    "accumulated_stalls": 0,
    "accumulated_forwards": 0
  }
}
```

All register and memory values are formatted as unsigned 32-bit hexadecimal strings.
