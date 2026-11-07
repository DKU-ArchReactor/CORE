#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
python -m grpc_tools.protoc -Iproto --python_out=. --grpc_python_out=. --descriptor_set_out=proto/contract.pb --include_imports proto/archreactor/v1/simulation.proto
# Canonical protobuf package remains archreactor.v1; Python distribution avoids
# collisions with each repository's application package named app.
mv archreactor/v1/simulation_pb2*.py archreactor_contract/v1/
rmdir archreactor/v1 archreactor
python - <<'PY'
from pathlib import Path
p = Path('archreactor_contract/v1/simulation_pb2_grpc.py')
p.write_text(p.read_text().replace('from archreactor.v1 import', 'from archreactor_contract.v1 import'))
PY
