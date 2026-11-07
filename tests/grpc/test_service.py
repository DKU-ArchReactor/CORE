import asyncio
import json
from pathlib import Path
import grpc
import pytest
from archreactor_contract.v1 import simulation_pb2 as pb, simulation_pb2_grpc as rpc
from service.server import Simulator, make_server
SAMPLE = (Path(__file__).parents[1] / 'program2.elf').read_bytes()


def request(**kwargs):
    values = dict(request_id='same-request', elf=SAMPLE, mode=pb.PIPELINE, max_cycles=2000)
    values.update(kwargs)
    return pb.RunSimulationRequest(**values)


def run_case(check, **options):
    async def run():
        simulator = Simulator(**options)
        server, _ = make_server(simulator)
        port = server.add_insecure_port('127.0.0.1:0')
        await server.start()
        try:
            async with grpc.aio.insecure_channel(f'127.0.0.1:{port}', options=[('grpc.max_receive_message_length', 8 * 1024 * 1024)]) as channel:
                await check(rpc.SimulatorStub(channel), simulator)
        finally:
            await server.stop(0)
    asyncio.run(run())


def test_sample_and_state_isolation():
    async def check(stub, simulator):
        responses = await asyncio.gather(*[stub.RunSimulation(request(), timeout=10) for _ in range(2)])
        assert responses[0].execution_id != responses[1].execution_id
        assert responses[0].result_json == responses[1].result_json
        for r in responses:
            data = json.loads(r.result_json)
            assert r.status == pb.COMPLETED
            assert 'ALL PASS' in data['console_output']
            assert r.result_schema_version == '1.0'
            assert data['summary']['executed_cycles'] == len(data['history'])
        assert simulator.active == 0 and not simulator.processes
    run_case(check)


def test_timing_metadata_preserves_result_contract():
    async def check(stub, simulator):
        call = stub.RunSimulation(request(), timeout=10)
        response = await call
        timings = {key: float(value) for key, value in await call.trailing_metadata()}
        assert response.status == pb.COMPLETED
        assert set(timings) == {'core-worker', 'core-load', 'core-sim', 'core-cpu', 'core-json'}
        assert all(value >= 0 for value in timings.values())
        assert timings['core-worker'] >= timings['core-load'] + timings['core-sim'] + timings['core-json'] - 0.01
        assert 'timing' not in json.loads(response.result_json)
    run_case(check)


@pytest.mark.parametrize('kwargs,code', [
    ({'elf': b'not-elf'}, grpc.StatusCode.INVALID_ARGUMENT),
    ({'elf': b'x' * (256 * 1024 + 1)}, grpc.StatusCode.RESOURCE_EXHAUSTED),
    ({'max_cycles': 2001}, grpc.StatusCode.INVALID_ARGUMENT),
    ({'mode': 0}, grpc.StatusCode.INVALID_ARGUMENT),
    ({'request_id': '\n'}, grpc.StatusCode.INVALID_ARGUMENT),
])
def test_rejected_inputs(kwargs, code):
    async def check(stub, simulator):
        with pytest.raises(grpc.aio.AioRpcError) as e:
            await stub.RunSimulation(request(**kwargs), timeout=10)
        assert e.value.code() == code
        assert simulator.active == 0
    run_case(check)


def test_cycle_limit():
    async def check(stub, simulator):
        r = await stub.RunSimulation(request(max_cycles=1), timeout=10)
        assert r.status == pb.CYCLE_LIMIT
        assert json.loads(r.result_json)['summary']['total_cycles'] == 1
    run_case(check)


def test_server_deadline_kills_worker():
    async def check(stub, simulator):
        with pytest.raises(grpc.aio.AioRpcError) as e:
            await stub.RunSimulation(request(), timeout=5)
        assert e.value.code() == grpc.StatusCode.DEADLINE_EXCEEDED
        await asyncio.sleep(0.3)
        assert simulator.active == 0 and not simulator.processes
    run_case(check, timeout=0.001)


def test_cancel_kills_worker_and_releases_capacity():
    async def check(stub, simulator):
        call = stub.RunSimulation(request(), timeout=10)
        for _ in range(100):
            if simulator.processes:
                break
            await asyncio.sleep(0.001)
        workers = list(simulator.processes)
        assert workers
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
        await asyncio.sleep(0.4)
        assert all(p.returncode is not None for p in workers)
        assert simulator.active == 0 and not simulator.processes
        assert (await stub.RunSimulation(request(), timeout=10)).status == pb.COMPLETED
    run_case(check)


def test_concurrency_limit():
    async def check(stub, simulator):
        first = stub.RunSimulation(request(), timeout=10)
        for _ in range(100):
            if simulator.active:
                break
            await asyncio.sleep(0.001)
        with pytest.raises(grpc.aio.AioRpcError) as e:
            await stub.RunSimulation(request(), timeout=10)
        assert e.value.code() == grpc.StatusCode.RESOURCE_EXHAUSTED
        await first
    run_case(check, concurrency=1)


def test_client_deadline_stops_computation():
    async def check(stub, simulator):
        call = stub.RunSimulation(request(), timeout=0.01)
        with pytest.raises(grpc.aio.AioRpcError) as error:
            await call
        assert error.value.code() == grpc.StatusCode.DEADLINE_EXCEEDED
        await asyncio.sleep(0.4)
        assert simulator.active == 0 and not simulator.processes
    run_case(check)
