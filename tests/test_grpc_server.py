"""Real RPC calls into the process-isolated engine adapter."""
from io import BytesIO
import json
from pathlib import Path
import uuid
import threading

import pytest

grpc = pytest.importorskip('grpc')
from elftools.elf.elffile import ELFFile
from grpc_health.v1 import health_pb2, health_pb2_grpc
from google.protobuf import descriptor_pb2

from archreactor.v1 import simulation_pb2 as pb, simulation_pb2_grpc as rpc
from server.grpc_server import create_server

REFERENCE = Path(__file__).with_name('program2.elf')


@pytest.fixture
def running_core():
    server = create_server()
    port = server.add_insecure_port('127.0.0.1:0')
    server.start()
    channel = grpc.insecure_channel(f'127.0.0.1:{port}')
    try:
        yield rpc.SimulatorStub(channel), channel
    finally:
        channel.close()
        server.stop(0).wait()


def request(mode=pb.SINGLE, elf=None, max_cycles=2000):
    return pb.RunSimulationRequest(request_id=str(uuid.uuid4()), mode=mode,
        elf=REFERENCE.read_bytes() if elf is None else elf, max_cycles=max_cycles)


def executable(*words):
    data = bytearray(REFERENCE.read_bytes())
    elf = ELFFile(BytesIO(data))
    text = elf.get_section_by_name('.text')
    data[24:28] = int(text['sh_addr']).to_bytes(4, 'little')
    instructions = list(words) + [0x00000013] * (text['sh_size'] // 4 - len(words))
    data[text['sh_offset']:text['sh_offset'] + text['sh_size']] = b''.join(word.to_bytes(4, 'little') for word in instructions)
    return bytes(data)


def test_reference_program_in_both_engines(running_core):
    stub, channel = running_core
    health = health_pb2_grpc.HealthStub(channel).Check(health_pb2.HealthCheckRequest(service='archreactor.v1.Simulator'))
    assert health.status == health_pb2.HealthCheckResponse.SERVING
    final = []
    for mode, clocks in [(pb.SINGLE, 97), (pb.PIPELINE, 134)]:
        body = request(mode=mode)
        response = stub.RunSimulation(body, timeout=5)
        result = json.loads(response.result_json)
        assert response.request_id == body.request_id
        assert response.status == pb.COMPLETED
        assert result['summary']['total_cycles'] == clocks
        assert result['summary']['instructions_executed'] == 97
        assert result['initial_state']['metrics']['accumulated_instructions'] == 0
        assert 'ALL PASS' in result['console_output']
        final.append(result['history'][-1]['global_result'])
    for field in ('registers', 'memory_snapshot', 'console_output'):
        assert final[0][field] == final[1][field]


@pytest.mark.parametrize('mode', [pb.SINGLE, pb.PIPELINE])
def test_cycle_limit_is_a_result_not_a_transport_failure(running_core, mode):
    response = running_core[0].RunSimulation(request(mode=mode, elf=executable(0x0000006F), max_cycles=7), timeout=5)
    result = json.loads(response.result_json)
    assert response.status == pb.CYCLE_LIMIT
    assert result['status'] == 'error'
    assert result['summary']['total_cycles'] == 7


def test_runtime_fault_on_last_allowed_clock_is_not_a_cycle_limit(running_core):
    response = running_core[0].RunSimulation(request(elf=executable(0x00202283), max_cycles=1), timeout=5)
    assert response.status == pb.SIMULATION_ERROR
    assert json.loads(response.result_json)['history'][0]['cycle_events']['runtime_error']['code'] == 'MEMORY_ALIGNMENT_ERROR'


@pytest.mark.parametrize('changes', [
    {'mode': pb.EXECUTION_MODE_UNSPECIFIED}, {'max_cycles': 0}, {'max_cycles': 2001},
    {'elf': b''}, {'elf': b'not an ELF'}, {'request_id': ''},
])
def test_invalid_requests_are_rejected(running_core, changes):
    body = request()
    for key, value in changes.items():
        setattr(body, key, value)
    with pytest.raises(grpc.RpcError) as error:
        running_core[0].RunSimulation(body, timeout=5)
    assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_oversized_elf_allocation_is_rejected_before_loading(running_core):
    data = bytearray(REFERENCE.read_bytes())
    elf = ELFFile(BytesIO(data))
    index = next(index for index, section in enumerate(elf.iter_sections()) if section.name == '.text')
    offset = elf['e_shoff'] + index * elf['e_shentsize'] + 20
    data[offset:offset + 4] = (65540).to_bytes(4, 'little')
    with pytest.raises(grpc.RpcError) as error:
        running_core[0].RunSimulation(request(elf=bytes(data)), timeout=5)
    assert error.value.code() == grpc.StatusCode.RESOURCE_EXHAUSTED


def test_concurrent_requests_have_separate_state_and_execution_ids(running_core):
    calls = [running_core[0].RunSimulation.future(request(elf=executable(word, 0x00A00893, 0x00000073)), timeout=5)
             for word in (0x02900293, 0x02A00293)]
    responses = [call.result() for call in calls]
    assert responses[0].execution_id != responses[1].execution_id
    for response, expected in zip(responses, (41, 42)):
        assert response.status == pb.COMPLETED
        result = json.loads(response.result_json)
        assert int(result['history'][-1]['global_result']['registers']['x5'], 16) == expected
        assert result['initial_state']['registers']['x5'] == '0x00000000'


def test_deadline_then_subsequent_request_recovers(running_core):
    with pytest.raises(grpc.RpcError) as error:
        running_core[0].RunSimulation(request(), timeout=0.001)
    assert error.value.code() == grpc.StatusCode.DEADLINE_EXCEEDED
    assert running_core[0].RunSimulation(request(), timeout=5).status == pb.COMPLETED


def test_contract_matches_frozen_be_descriptor():
    baseline = descriptor_pb2.FileDescriptorSet.FromString((Path(__file__).parents[1] / 'contracts/v1-baseline.pb').read_bytes())
    current = descriptor_pb2.FileDescriptorProto.FromString(pb.DESCRIPTOR.serialized_pb)
    # Runtime descriptors omit explicit default JSON names that protoc writes
    # into descriptor sets. Compare their effective names, not serialization.
    for message in current.message_type:
        runtime = pb.DESCRIPTOR.message_types_by_name[message.name]
        for field in message.field:
            field.json_name = runtime.fields_by_name[field.name].json_name
    assert current in baseline.file


def test_capacity_limit_and_recovery(monkeypatch):
    from server.grpc_server import Simulator
    entered = threading.Event()
    release = threading.Event()
    lock = threading.Lock()
    active = []

    def hold(self, payload, context):
        with lock:
            active.append(payload['execution_id'])
            if len(active) == 2:
                entered.set()
        assert release.wait(3)
        return {'execution_status': 'COMPLETED', 'result': {'status': 'halted'}}

    monkeypatch.setattr(Simulator, '_execute', hold)
    server = create_server()
    port = server.add_insecure_port('127.0.0.1:0')
    server.start()
    channel = grpc.insecure_channel(f'127.0.0.1:{port}')
    stub = rpc.SimulatorStub(channel)
    try:
        calls = [stub.RunSimulation.future(request(), timeout=5) for _ in range(2)]
        assert entered.wait(3)
        with pytest.raises(grpc.RpcError) as error:
            stub.RunSimulation(request(), timeout=2)
        assert error.value.code() == grpc.StatusCode.RESOURCE_EXHAUSTED
        release.set()
        assert all(call.result().status == pb.COMPLETED for call in calls)
        assert stub.RunSimulation(request(), timeout=2).status == pb.COMPLETED
    finally:
        release.set()
        channel.close()
        server.stop(0).wait()


def test_worker_process_is_reaped_after_timeout(monkeypatch):
    from server import grpc_server
    processes = []
    original = grpc_server.subprocess.Popen

    def record(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    class Aborted(Exception):
        pass

    class Deadline:
        def time_remaining(self):
            return 0.00001
        def is_active(self):
            return True
        def abort(self, code, message):
            assert code == grpc.StatusCode.DEADLINE_EXCEEDED
            raise Aborted()

    monkeypatch.setattr(grpc_server.subprocess, 'Popen', record)
    with pytest.raises(Aborted):
        grpc_server.Simulator()._execute({}, Deadline())
    assert processes and all(process.poll() is not None for process in processes)
