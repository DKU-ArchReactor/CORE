"""Check public BE -> deployed CORE; keep guest tokens and URLs in memory."""
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen

BASE = 'https://d1j3nkcez6kncs.cloudfront.net'


def call(path, payload=None):
    req = Request(BASE + path, data=None if payload is None else json.dumps(payload).encode(),
                  headers={'Content-Type': 'application/json', 'Cache-Control': 'no-cache'})
    with urlopen(req, timeout=35) as response:
        return response.status, json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=('before', 'after'), required=True)
    parser.add_argument('--expected-version')
    args = parser.parse_args()
    http, health = call('/')
    assert http == 200 and health['status'] == 'ok'
    http, build = call('/api/v1/build/compile', {
        'content':'int main(void) { return 42; }', 'lang':'c', 'compiler_opt':'-O0', 'compile_profile':'rv32im'})
    assert http == 201 and build['status'] == 'success' and build['simulation_token']
    token = build['simulation_token']
    report = {'checked_at':datetime.now(timezone.utc).isoformat(), 'phase':args.phase, 'modes':{}}
    results = []
    for mode in ('single', 'pipeline'):
        http, response = call('/api/v1/simulation/run', {'simulation_token':token, 'mode':mode, 'max_cycles':2000})
        assert http == 200 and response['execution_status'] == 'COMPLETED'
        result = response['result']
        assert result['simulator']['mode'] == mode
        if args.expected_version:
            assert response['core_version'] == args.expected_version
        if args.phase == 'after':
            assert result['simulator']['pipeline_model'] == ('single-cycle' if mode == 'single' else '5-stage-in-order')
            assert result['initial_state'] and result['program']['instructions']
            if mode == 'single':
                assert result['summary']['total_cycles'] == result['summary']['instructions_executed']
        final = result['history'][-1]['global_result']
        assert int(final['registers']['x10'], 16) == 42
        results.append(result)
        limit_http, limited = call('/api/v1/simulation/run', {'simulation_token':token, 'mode':mode, 'max_cycles':1})
        assert limit_http == 200 and limited['execution_status'] == 'CYCLE_LIMIT'
        assert limited['result']['summary']['total_cycles'] == 1
        report['modes'][mode] = {'http':http, 'core_version':response['core_version'],
            'execution_status':response['execution_status'], 'model':result['simulator']['pipeline_model'],
            'cycles':result['summary']['total_cycles'], 'instructions':result['summary']['instructions_executed'],
            'return_value':42, 'cycle_limit':'PASS'}
    for key in ('registers', 'memory_snapshot', 'console_output'):
        assert results[0]['history'][-1]['global_result'][key] == results[1]['history'][-1]['global_result'][key]
    report['status'] = 'PASS'
    output = Path(__file__).resolve().parents[1] / 'dist' / ('public-api-' + args.phase + '.json')
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
