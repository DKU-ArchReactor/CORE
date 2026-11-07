# ArchReactor

ArchReactor is an educational RV32IM simulator core for computer architecture courses.

The current repository focuses on the Python simulation core: instruction decode/execute, memory, single-step execution, 5-stage pipeline history, hazard events, and validation of supported RISC-V instructions.

## Goals

ArchReactor is built for students who need to inspect how a small C/RISC-V program moves through a CPU model:

- instruction fetch, decode, execute, memory, writeback
- register and memory state changes
- load-use stalls
- EX/MEM and MEM/WB forwarding
- branch and jump flushes
- runtime errors such as misaligned memory access

It is not a full RISC-V machine emulator. The supported subset is intentionally constrained for teaching.

## Current Components

- `app/decoder.py`: RV32IM instruction decoder
- `app/executor.py`: ALU and branch operation semantics
- `app/memory.py`: word, halfword, and byte memory access
- `app/state.py`: ELF/raw program loading and CPU state creation
- `app/simulator.py`: public simulation API and mode dispatch
- `app/single_cycle_engine.py`: one complete instruction per clock, without pipeline buffers
- `app/pipeline_engine.py`: 5-stage execution, stalls, forwarding, and flushes
- `app/engine_common.py`: shared instruction semantics and clock-history snapshots
- `app/validator.py`: pre-simulation instruction support validation
- `tests/tester.py`: CLI runner that writes `simulation_result.json`

## Service deployment

Pull requests run engine, gRPC contract and container checks. Changes pushed or merged
to `develop` deploy the CORE gRPC service to the existing ECS service in Seoul using
GitHub OIDC and CodeBuild. See [deployment and rollback](docs/grpc-deployment.md)
for setup, status artifacts and recovery instructions.

## Quick Check

Run the full local verification suite:

```bash
scripts/check.sh
```

This runs:

- unit tests
- ELF validation
- single-mode smoke simulation
- pipeline-mode smoke simulation

## Run the Reference Program

```bash
python tests/tester.py --input tests/program2.elf --mode single --output-dir results
python tests/tester.py --input tests/program2.elf --mode pipeline --output-dir tests/results
```

Expected console output:

```text
Advanced Pipeline Test Start...
Advanced Test Result: ALL PASS
```

## Compile C for ArchReactor

Use the compile wrapper:

```bash
scripts/compile_rv32im.sh examples/01_arithmetic.c examples/01_arithmetic.elf
```

The wrapper expects `riscv64-unknown-elf-gcc` on `PATH`. If your compiler is elsewhere:

```bash
RISCV_CC=/path/to/riscv64-unknown-elf-gcc scripts/compile_rv32im.sh examples/01_arithmetic.c examples/01_arithmetic.elf
```

The wrapper compiles with a constrained RV32IM profile and then validates the produced ELF before simulation.

## Teaching Examples

Small C examples live in `examples/`:

- `01_arithmetic.c`
- `02_load_use_stall.c`
- `03_forwarding.c`
- `04_branch_flush.c`
- `05_function_call.c`
- `06_byte_halfword_memory.c`

See `examples/README.md` for usage.

## Documentation

- `docs/supported-subset.md`: supported ISA, syscall subset, memory model, pipeline assumptions, recommended C subset
- `docs/history-schema.md`: JSON result and cycle history schema for UI/backend consumers
- `docs/engine-verification.md`: engine separation, regression coverage, and frontend integration requirements

## Execution Modes

`single` executes one instruction through IF/ID/EX/MEM/WB within one clock.
Each history entry contains that instruction's stage activity and its completed
register/memory state. There are no pipeline stalls, forwarding, flush bubbles,
or pipeline buffers in this mode.

`pipeline` advances overlapping instructions through five stages. Use
`stage_activity` for work performed during the clock and `buffers` for pipeline
contents after the clock. A populated WB buffer means an instruction is waiting
for writeback on the next clock, not that its register write has completed.

## Simulation History

Each cycle records:

- `stage_activity`: what IF/ID/EX/MEM/WB did during the clock
- `buffers`: pipeline register state after the clock edge
- `cycle_events`: stall, forwarding, control hazard, runtime error
- `global_result`: architectural state snapshot

For teaching UI, prefer `stage_activity` and `cycle_events`.

## Development

Install dependencies:

```bash
pip install -r requirements.txt
```

Run tests:

```bash
pytest -q
```

Validate an ELF or raw instruction file:

```bash
python -m app.validator tests/program2.elf
```

Run a simulation:

```bash
python tests/tester.py --input tests/program2.elf --mode pipeline --history
```

## Docker

The Dockerfile is for test/CI-style execution of the Python core:

```bash
docker build -t archreactor-core .
docker run --rm archreactor-core
```
