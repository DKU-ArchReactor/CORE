"""Regenerate Python bindings without changing the BE archreactor.v1 contract."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
subprocess.run([
    sys.executable, '-m', 'grpc_tools.protoc', '-I', str(root / 'contracts'),
    '--python_out', str(root), '--grpc_python_out', str(root),
    str(root / 'contracts/archreactor/v1/simulation.proto'),
], check=True)
