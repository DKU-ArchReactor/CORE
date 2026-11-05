# Engine separation and verification

## Scope and baseline

Based on CORE `main` at `1bf2957eb2d647a6b8c3983c3fa945a5580dbb83`.
The change is maintained on branch `fix/separate-single-cycle-engine`.
It has not been merged to `main` or deployed.

The original 38 tests passed, but single mode reused the pipeline engine,
serializing one instruction through its buffers instead of completing it in
one clock. In addition, `buffers.WB` represented an instruction waiting for
writeback, while `global_result` represented the state after the current clock.
Treating that buffer as a completed instruction selected a state one clock too
early.

## Changes

- `single_cycle_engine.py` completes one instruction per clock. All stage
  activity refers to that instruction; the same history item contains the
  resulting architectural state. Pipeline buffers stay empty.
- `pipeline_engine.py` owns overlapping execution, stalls, forwarding, and
  flushing. A taken redirect overrides a stall on the discarded path. A
  terminating syscall prevents younger memory writes and register writeback.
- `engine_common.py` shares instruction semantics, memory access, syscall
  handling, and snapshot formatting. Effective addresses and next-PC values
  wrap to 32 bits. Snapshots are copied before being retained in history.
- The decoder clears unused source-register fields so immediate bits cannot
  trigger false hazards or forwarding.
- Faulting instructions do not retire. Halt/error is terminal for the public
  tick API. Cycle-limit diagnostics report the actual requested limit.

The public imports `create_state`, `core_single_tick`, and `run_simulation`
remain available. See [history-schema.md](history-schema.md) for mode-specific
history semantics and metadata.

## Verification

Run from the CORE directory with project dependencies installed:

```bash
python -m pytest -q
python -m app.validator tests/program2.elf
python tests/tester.py --input tests/program2.elf --mode single --output-dir results/single
python tests/tester.py --input tests/program2.elf --mode pipeline --output-dir results/pipeline
git diff --check
```

Results: **187 tests passed**. Before implementation, nine cases in the
initial regression suite failed against the original engine.

Coverage includes one-clock retirement, same-clock WB/state agreement,
dependent arithmetic, RV32M edge cases, signed/unsigned loads, partial stores,
high memory addresses, all six conditional branches, repeated loop iterations,
JAL/JALR, load-use stalls, false immediate dependencies, flush priority,
syscall ordering, termination, runtime errors, immutable history, and cycle
limits.

Both checked-in reference ELFs are also run in three configurations: single,
pipeline with forwarding, and pipeline without forwarding. Final registers,
memory, console output, and retired instruction counts must match across all
three configurations. Their console output is checked against explicit
expected success strings.

For `tests/program2.elf` with default forwarding:

| Result | Single | Pipeline |
|---|---:|---:|
| Retired instructions | 97 | 97 |
| Clocks | 97 | 134 |
| Stalls | 0 | 9 |
| Forwarded operands | 0 | 44 |
| Control hazard redirects | 0 | 8 |

Both modes halt with `Advanced Test Result: ALL PASS`, and their final
registers, memory, and console output are identical.

## Frontend integration

FE branch `fix/simulation-information` now requests both modes separately and
steps through dynamic history rather than searching WB buffers. The frontend
uses current-clock `stage_activity` and can import local CORE JSON results.
See `FE/doc/simulation-information-audit.md` for the project-wide audit.

CORE now returns initial state, the input fingerprint, actual instruction
addresses/words, and ELF section ranges so consumers do not invent these values.
The pipeline no longer counts an empty setup clock; independent N-instruction
programs take N+4 clocks. A WB value is available to ID in the same clock.

The deployed backend/CORE service has not been updated or verified. BE branch
`fix/simulation-information` (local worktree `BE-audit`) adds response mode/status
validation and tests transport of the real CORE output through a local fixture
gRPC server. This is not a production deployment test or a new production CORE
gRPC server implementation.
