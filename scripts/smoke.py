"""Validate both develop engines through the production gRPC adapter."""
import json
from pathlib import Path
import sys
import grpc
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from archreactor_contract.v1 import simulation_pb2 as pb, simulation_pb2_grpc as rpc


def main():
    elf = (Path(__file__).resolve().parents[1] / 'tests/program2.elf').read_bytes()
    results = []
    with grpc.insecure_channel(sys.argv[1], options=[('grpc.max_receive_message_length', 8*1024*1024)]) as channel:
        stub = rpc.SimulatorStub(channel)
        for mode, name, model, cycles in [(pb.SINGLE, 'single', 'single-cycle', 97),
                                         (pb.PIPELINE, 'pipeline', '5-stage-in-order', 134)]:
            response = stub.RunSimulation(pb.RunSimulationRequest(
                request_id='deploy-smoke-' + name, elf=elf, mode=mode, max_cycles=2000), timeout=12)
            result = json.loads(response.result_json)
            assert response.status == pb.COMPLETED and 'ALL PASS' in result['console_output']
            assert result['simulator']['mode'] == name and result['simulator']['pipeline_model'] == model
            assert result['summary']['total_cycles'] == len(result['history']) == cycles
            assert result['summary']['instructions_executed'] == 97
            assert result['initial_state'] and result['program']['instructions']
            limited = stub.RunSimulation(pb.RunSimulationRequest(
                request_id='deploy-smoke-limit-' + name, elf=elf, mode=mode, max_cycles=1), timeout=12)
            assert limited.status == pb.CYCLE_LIMIT
            assert json.loads(limited.result_json)['summary']['total_cycles'] == 1
            results.append(result)
            print(json.dumps({'status':'PASS', 'mode': name, 'core_version':response.core_version, 'cycles':cycles}))
        for key in ('registers', 'memory_snapshot', 'console_output'):
            assert results[0]['history'][-1]['global_result'][key] == results[1]['history'][-1]['global_result'][key]


if __name__ == '__main__':
    main()
