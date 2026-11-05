# CORE gRPC server

This adapter exposes the existing engines to BE without importing CORE into the
BE process. It implements the unchanged `archreactor.v1.Simulator/RunSimulation`
contract. BE's generated client and `contracts/v1-baseline.pb` remain compatible.

## Run locally

Install dependencies from this CORE checkout and launch the server:

```powershell
python -m pip install -r requirements-server.txt
$env:CORE_VERSION = (git rev-parse HEAD).Trim()
python -m server.grpc_server --host 127.0.0.1 --port 50051
```

In the BE process set `CORE_GRPC_TARGET=127.0.0.1:50051`. BE remains responsible
for HTTP validation, build ownership, token authorization, and S3 ELF downloads.
The CORE server receives ELF bytes, not user-supplied filesystem paths or URLs.

## Request and result

- `request_id`: nonempty correlation string, at most 128 characters.
- `elf`: little-endian RV32 executable ELF bytes.
- `mode`: `SINGLE` or `PIPELINE`, dispatched to the matching engine.
- `max_cycles`: integer 1–2000.

The response echoes `request_id`, generates an independent `execution_id`, and
includes `core_version`, `result_schema_version`, and UTF-8 `result_json`.
`CORE_VERSION` defaults to `development` if not supplied; deployments should set
it to the exact source commit. The JSON preserves `initial_state`, `program`,
`simulator`, `summary`, `history`, and `console_output` without reconstructing
the simulation history from WB buffers.

| Execution outcome | RPC response status | JSON status |
|---|---|---|
| Program halts | `COMPLETED` | `halted` |
| Clock budget exhausted | `CYCLE_LIMIT` | `error` |
| Runtime memory/instruction fault | `SIMULATION_ERROR` | `error` |

A fault on the last allowed clock remains `SIMULATION_ERROR`, not `CYCLE_LIMIT`.
Invalid input is an RPC `INVALID_ARGUMENT`; resource/capacity limits produce
`RESOURCE_EXHAUSTED`. Unexpected worker failures produce `INTERNAL`.

## Isolation and limits

Every execution runs in a fresh subprocess and calls `delete_state` in `finally`.
The parent terminates/reaps the worker on cancellation or timeout; this does not
depend on the simulator returning normally.

- ELF input: 256 KiB; allocated ELF sections: 64 KiB checked before loading.
- Simulated instruction/data words: at most 64 KiB checked before returning.
- RPC result: 8 MiB including the envelope; JSON is bounded in the worker.
- Worker lifetime: at most 10 seconds, or the caller's earlier deadline.
- Concurrent simulations: 2 per server process; additional requests fail promptly.
- Linux worker address space: 384 MiB. This OS memory cap is not available on Windows.
- No compiler, submitted host code, or shell runs inside the worker.

Standard gRPC health checks report the `archreactor.v1.Simulator` service.
The local CLI binds loopback by default. Transport is plaintext for a private
BE-to-CORE network, matching the existing deployment contract; do not expose the
port as a public unauthenticated service.

## Container

```bash
docker build -f Dockerfile.server --build-arg CORE_VERSION=$(git rev-parse HEAD) -t archreactor-core-server .
docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges -p 127.0.0.1:50051:50051 archreactor-core-server
```

This adds a runnable image, not AWS infrastructure or an automatic deployment.

## Verify

```bash
pip install -r requirements-server-dev.txt
python scripts/generate_contracts.py
git diff --exit-code -- archreactor
pytest -q
```

Tests call the real server and workers for both engines, cycle limits, runtime
faults, malformed requests, allocation limits, independent concurrent state,
capacity rejection/recovery, deadline recovery, and worker cleanup. The frozen
BE descriptor is checked with protobuf's effective default JSON names normalized.
