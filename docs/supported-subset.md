# ArchReactor Supported Subset

This document defines the current educational execution contract. ArchReactor is not a full RISC-V system emulator; it simulates a constrained RV32IM subset intended for computer architecture classes.

## Compile Profile

Use the project compiler wrapper:

```bash
scripts/compile_rv32im.sh tests/test_program2.c tests/program2.elf
```

The wrapper uses:

```bash
riscv64-unknown-elf-gcc \
  -march=rv32im \
  -mabi=ilp32 \
  -O0 \
  -ffreestanding \
  -nostdlib \
  -nostartfiles \
  -fno-pic \
  -fno-pie \
  -fno-builtin \
  -fno-inline \
  -Wl,-Ttext=0x10000
```

Set `RISCV_CC=/path/to/riscv64-unknown-elf-gcc` if the compiler is not on `PATH`.

After compilation, the wrapper runs the ArchReactor validator. Unsupported instructions are rejected before simulation.

Small teaching examples are available under `examples/`.

Validation errors include structured fields:

- `code`
- `address`
- `raw_word`
- `message`
- `reason`

Current validation error codes:

- `UNSUPPORTED_INSTRUCTION`
- `MISSING_TEXT_SECTION`

## Supported Instructions

Arithmetic and logic:

- `add`, `sub`
- `and`, `or`, `xor`
- `sll`, `srl`, `sra`
- `slt`, `sltu`
- `addi`, `andi`, `ori`, `xori`
- `slti`, `sltiu`
- `slli`, `srli`, `srai`

RV32M:

- `mul`, `mulh`, `mulhsu`, `mulhu`
- `div`, `divu`
- `rem`, `remu`

Memory:

- `lb`, `lh`, `lw`
- `lbu`, `lhu`
- `sb`, `sh`, `sw`

Control flow:

- `beq`, `bne`, `blt`, `bge`, `bltu`, `bgeu`
- `jal`, `jalr`

Address and system:

- `lui`, `auipc`
- `ecall`

## Syscalls

The simulator intercepts a small educational syscall subset:

- `a7 = 1`: print signed integer in `a0`
- `a7 = 4`: print null-terminated string at address `a0`
- `a7 = 10`: halt simulation

Other syscall numbers are ignored and appended as `[ecall N ignored]`.

## Memory Model

Instruction memory is loaded from `.text`.

Data memory is loaded from:

- `.rodata`
- `.data`
- `.sdata`
- `.bss` as zero-filled words
- `.sbss` as zero-filled words

The initial stack pointer is:

```text
sp = 0x7FFFEFFC
```

Word and halfword alignment is enforced:

- `lw`, `sw`, string word reads: 4-byte aligned
- `lh`, `lhu`, `sh`: 2-byte aligned
- `lb`, `lbu`, `sb`: byte aligned

Alignment errors are recorded in `cycle_events.runtime_error` and stop the simulation with `status = "error"`.

## Pipeline Model

Pipeline mode models a 5-stage in-order pipeline:

- IF
- ID
- EX
- MEM
- WB

Current assumptions:

- Branch and jump resolution happens in EX.
- Taken branches and jumps flush IF and ID.
- Not-taken branches are recorded but do not flush.
- Load-use hazards introduce a 1-cycle stall with forwarding enabled.
- EX/MEM and MEM/WB forwarding are modeled and recorded per operand.

Cycle history separates:

- `stage_activity`: what each stage did during the current clock
- `buffers`: pipeline register state after the clock edge
- `cycle_events`: stall, forwarding, control hazard, and runtime error events
- `global_result`: architectural state snapshot

## Recommended C Subset

Prefer:

- `int` arithmetic
- simple arrays and pointers
- `if`, `for`, function calls
- explicit inline `ecall` helpers
- small `char` or `short` examples only when teaching byte/halfword memory

Avoid:

- standard library calls
- dynamic allocation
- floating point
- atomics
- CSR access
- interrupts/exceptions beyond the recorded runtime errors
- 64-bit data types unless the resulting instructions pass validation
