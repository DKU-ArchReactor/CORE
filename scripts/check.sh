#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[1/4] Running unit tests"
pytest -q

echo "[2/4] Validating reference ELF"
python -m app.validator tests/program2.elf

echo "[3/4] Running single-mode smoke test"
python tests/tester.py \
  --input tests/program2.elf \
  --mode single \
  --max-clocks 2000 \
  --output-dir results

echo "[4/4] Running pipeline-mode smoke test"
python tests/tester.py \
  --input tests/program2.elf \
  --mode pipeline \
  --max-clocks 2000 \
  --output-dir tests/results

echo "ArchReactor check completed successfully."
