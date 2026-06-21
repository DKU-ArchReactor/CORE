# ArchReactor C Examples

These examples are intentionally small. Each file targets one computer architecture concept and should be compiled with the project wrapper:

```bash
scripts/compile_rv32im.sh examples/01_arithmetic.c examples/01_arithmetic.elf
python tests/tester.py --input examples/01_arithmetic.elf --mode pipeline --history
```

The examples avoid the C standard library and use ArchReactor's educational `ecall` subset directly.

## Files

- `01_arithmetic.c`: integer arithmetic and RV32M multiply/divide/remainder
- `02_load_use_stall.c`: load-use data hazard and 1-cycle stall
- `03_forwarding.c`: ALU result forwarding without a stall
- `04_branch_flush.c`: taken branch and control hazard flush
- `05_function_call.c`: `jal`/`jalr` through a noinline function call
- `06_byte_halfword_memory.c`: `sb/sh/lb/lh/lbu/lhu` style memory behavior

## Expected Pattern

Each example prints a start line and either `PASS` or `FAIL`.

Run single and pipeline modes to compare architectural correctness and cycle-level behavior:

```bash
python tests/tester.py --input examples/02_load_use_stall.elf --mode single
python tests/tester.py --input examples/02_load_use_stall.elf --mode pipeline --history
```

For teaching UI work, prefer the JSON fields documented in `docs/history-schema.md`.
