"""Guard production against wrong identities, infrastructure changes and failed rollouts."""
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('core_deploy', ROOT / 'scripts/deploy.py')
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


def test_wrong_account_cannot_mutate_or_read_workloads():
    session = MagicMock()
    session.client.return_value.get_caller_identity.return_value = {'Account': '731732399204'}
    with pytest.raises(ValueError, match='Wrong AWS account'):
        deploy.deploy(session, None, {})
    assert [call.args[0] for call in session.client.call_args_list] == ['sts']


def test_local_deploy_always_uses_project_profile(monkeypatch):
    session = MagicMock()
    monkeypatch.setattr(deploy.boto3, 'Session', session)
    deploy.make_session(False, {'AWS_PROFILE': 'default'})
    session.assert_called_once_with(profile_name='archreactor-new', region_name='ap-northeast-2')


def github_env():
    return {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'DKU-ArchReactor/CORE',
            'GITHUB_REF': 'refs/heads/develop', 'GITHUB_EVENT_NAME': 'push',
            'AWS_ACCESS_KEY_ID': 'test', 'AWS_SECRET_ACCESS_KEY': 'test', 'AWS_SESSION_TOKEN': 'test'}


@pytest.mark.parametrize('key,value', [('GITHUB_REPOSITORY', 'fork/CORE'),
    ('GITHUB_REF', 'refs/heads/main'), ('GITHUB_EVENT_NAME', 'pull_request'),
    ('AWS_PROFILE', 'default'), ('AWS_SESSION_TOKEN', '')])
def test_ci_refuses_untrusted_context(key, value):
    env = github_env()
    env[key] = value
    with pytest.raises(ValueError):
        deploy.make_session(True, env)


def test_ci_uses_oidc_environment(monkeypatch):
    session = MagicMock()
    monkeypatch.setattr(deploy.boto3, 'Session', session)
    deploy.make_session(True, github_env())
    session.assert_called_once_with(region_name='ap-northeast-2')


def change(*resources):
    return {'Status': 'CREATE_COMPLETE', 'ExecutionStatus': 'AVAILABLE',
            'Changes': [{'ResourceChange': {'LogicalResourceId': name, 'Action': action}}
                        for name, action in resources]}


def test_accepts_only_core_task_and_service_update():
    deploy.validate_changes(change(('Task', 'Modify'), ('Service', 'Modify')))


@pytest.mark.parametrize('changes', [change(('SecurityGroup', 'Modify')), change(('ExecutionRole', 'Modify')),
    change(('Service', 'Remove')), change(('Task', 'Add')), change(),
    dict(change(('Task', 'Modify')), NextToken='more')])
def test_rejects_unexpected_or_incomplete_change_set(changes):
    with pytest.raises(ValueError):
        deploy.validate_changes(changes)


@pytest.mark.parametrize('value', ['latest', 'sha256:abcd', 'sha256:' + 'g'*64, 'sha256:' + 'a'*64 + '\n'])
def test_rollback_requires_exact_digest(value):
    with pytest.raises(ValueError):
        deploy.validate_digest(value)


def test_wait_fails_after_rollback_instead_of_reporting_success(monkeypatch):
    monkeypatch.setattr(deploy.time, 'sleep', lambda _: None)
    states = iter([{'StackStatus': 'UPDATE_ROLLBACK_IN_PROGRESS'}, {'StackStatus': 'UPDATE_ROLLBACK_COMPLETE'}])
    with pytest.raises(RuntimeError, match='UPDATE_ROLLBACK_COMPLETE'):
        deploy.wait_until(lambda: next(states), lambda s: s['StackStatus'] == 'UPDATE_COMPLETE',
            lambda s: not s['StackStatus'].endswith('_IN_PROGRESS') and s['StackStatus'] != 'UPDATE_COMPLETE')
