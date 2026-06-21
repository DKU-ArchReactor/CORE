#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 <input.c> [output.elf]" >&2
  exit 2
fi

INPUT="$1"
OUTPUT="${2:-${INPUT%.c}.elf}"
CC="${RISCV_CC:-riscv64-unknown-elf-gcc}"

if [[ ! -f "$INPUT" ]]; then
  echo "Input C file not found: $INPUT" >&2
  exit 2
fi

if ! command -v "$CC" >/dev/null 2>&1; then
  echo "RISC-V GCC not found: $CC" >&2
  echo "Set RISCV_CC=/path/to/riscv64-unknown-elf-gcc or install a RISC-V ELF toolchain." >&2
  exit 127
fi

"$CC" \
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
  -Wl,-Ttext=0x10000 \
  -o "$OUTPUT" \
  "$INPUT"

python -m app.validator "$OUTPUT"
echo "Wrote validated RV32IM ELF: $OUTPUT"
