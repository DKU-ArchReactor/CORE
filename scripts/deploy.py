"""Build and deploy only the existing CORE service; retain an explicit rollback record."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

import boto3
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT, REGION = '242925688392', 'ap-northeast-2'
BUCKET = f'elasticbeanstalk-{REGION}-{ACCOUNT}'
REPO = 'capstone/archreactor-core'
STACK = 'archreactor-simulator-service'
SERVICE = 'archreactor-simulator'
READY = {'CREATE_COMPLETE', 'UPDATE_COMPLETE', 'UPDATE_ROLLBACK_COMPLETE'}


def wait_until(read, accept, fail, timeout=1200, interval=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = read()
        if accept(result):
            return result
        if fail(result):
            raise RuntimeError('AWS operation failed: ' + json.dumps(result, default=str))
        time.sleep(interval)
    raise TimeoutError('AWS operation still pending; inspect its state before retrying')


def make_session(github_actions, environ=os.environ):
    if github_actions:
        expected = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'DKU-ArchReactor/CORE',
                    'GITHUB_REF': 'refs/heads/develop'}
        if any(environ.get(k) != v for k, v in expected.items()):
            raise ValueError('OIDC deployment is allowed only from DKU-ArchReactor/CORE develop')
        if environ.get('GITHUB_EVENT_NAME') not in {'push', 'workflow_dispatch'}:
            raise ValueError('Pull request jobs cannot deploy')
        # configure-aws-credentials exports short-lived OIDC credentials only to this job.
        if not all(environ.get(k) for k in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN')):
            raise ValueError('Missing temporary GitHub Actions credentials')
        if environ.get('AWS_PROFILE') or environ.get('AWS_DEFAULT_PROFILE'):
            raise ValueError('GitHub Actions must not select a local AWS profile')
        return boto3.Session(region_name=REGION)
    return boto3.Session(profile_name='archreactor-new', region_name=REGION)


def validate_digest(value):
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', value):
        raise ValueError('Expected an immutable sha256 image digest')
    return value


def validate_changes(change):
    if change['Status'] != 'CREATE_COMPLETE' or change['ExecutionStatus'] != 'AVAILABLE':
        raise ValueError('Change set is not ready')
    changes = change.get('Changes', [])
    if not changes or change.get('NextToken'):
        raise ValueError('Empty or incomplete change set')
    for item in changes:
        resource = item['ResourceChange']
        if resource['LogicalResourceId'] not in {'Task', 'Service'} or resource['Action'] != 'Modify':
            raise ValueError('Unexpected infrastructure change; refusing execution')


def save(record):
    out = ROOT / 'dist/deployment.json'
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(record, indent=2) + '\n')


def build_image(session, config, record):
    package = json.loads(subprocess.check_output([sys.executable, 'scripts/package-source.py'], cwd=ROOT, text=True))
    tag = package['tag']
    record.update(version=tag, source_sha256=package['sha256'], commit=package['commit'])
    save(record)
    ecr = session.client('ecr', config=config)
    try:
        details = ecr.describe_images(repositoryName=REPO, imageIds=[{'imageTag': tag}])['imageDetails'][0]
        # Immutable tags identify the exact source archive; a rerun can safely reuse it.
        return details['imageDigest']
    except ecr.exceptions.ImageNotFoundException:
        pass
    key = f'core-source/{tag}.zip'
    s3 = session.client('s3', config=config)
    s3.upload_file(package['file'], BUCKET, key, ExtraArgs={'ServerSideEncryption': 'AES256'})
    builder = session.client('codebuild', config=config)
    build = builder.start_build(
        projectName='archreactor-core-image-build', sourceLocationOverride=f'{BUCKET}/{key}',
        environmentVariablesOverride=[{'name': 'IMAGE_TAG', 'value': tag, 'type': 'PLAINTEXT'}],
        timeoutInMinutesOverride=20, queuedTimeoutInMinutesOverride=5,
        idempotencyToken=uuid.uuid4().hex)['build']
    record.update(build_id=build['id'], status='BUILD_IN_PROGRESS')
    save(record)
    print('Build: ' + build['id'], flush=True)
    wait_until(lambda: builder.batch_get_builds(ids=[build['id']])['builds'][0],
               lambda b: b['buildStatus'] == 'SUCCEEDED',
               lambda b: b['buildStatus'] not in {'IN_PROGRESS', 'SUCCEEDED'}, timeout=1600)
    return ecr.describe_images(repositoryName=REPO, imageIds=[{'imageTag': tag}])['imageDetails'][0]['imageDigest']


def diagnose_failure(ecs):
    print("=== DEPLOYMENT DIAGNOSTICS ===", flush=True)
    try:
        td = ecs.describe_task_definition(taskDefinition='archreactor-simulator')
        print("--- ECS Task Definition Details ---", flush=True)
        print(f"Latest TaskDef ARN: {td.get('taskDefinition', {}).get('taskDefinitionArn')}", flush=True)
        print(f"ExecutionRoleArn: {td.get('taskDefinition', {}).get('executionRoleArn')}", flush=True)
        for c in td.get('taskDefinition', {}).get('containerDefinitions', []):
            print(f"Container: {c.get('name')}, Image: {c.get('image')}", flush=True)
    except Exception as e:
        print(f"Could not retrieve task definition: {e}", flush=True)

    try:
        services = ecs.describe_services(cluster=SERVICE, services=[SERVICE]).get('services', [])
        if services:
            print("--- ECS Service Events (Recent 10) ---", flush=True)
            for ev in services[0].get('events', [])[:10]:
                print(f"[{ev.get('createdAt')}] {ev.get('message')}", flush=True)
    except Exception as e:
        print(f"Could not retrieve ECS service events: {e}", flush=True)

    try:
        tasks = list(ecs.get_paginator('list_tasks').paginate(cluster=SERVICE, serviceName=SERVICE, desiredStatus='STOPPED').search('taskArns[]'))
        if tasks:
            print("--- ECS Recent Stopped Tasks ---", flush=True)
            stopped = ecs.describe_tasks(cluster=SERVICE, tasks=tasks[:5]).get('tasks', [])
            for t in stopped:
                print(f"Task: {t.get('taskArn')}, StopCode: {t.get('stopCode')}, StoppedReason: {t.get('stoppedReason')}", flush=True)
                for c in t.get('containers', []):
                    print(f"  Container: {c.get('name')}, ExitCode: {c.get('exitCode')}, Reason: {c.get('reason')}", flush=True)
    except Exception as e:
        print(f"Could not retrieve stopped tasks: {e}", flush=True)
    print("===============================", flush=True)


def deploy(session, rollback, record):
    config = Config(retries={'mode': 'standard', 'total_max_attempts': 4}, connect_timeout=5, read_timeout=30)
    sts = session.client('sts', config=config)
    if sts.get_caller_identity()['Account'] != ACCOUNT:
        raise ValueError('Wrong AWS account; refusing any mutation')
    cfn = session.client('cloudformation', config=config)
    ecr = session.client('ecr', config=config)
    ecs = session.client('ecs', config=config)
    stack = cfn.describe_stacks(StackName=STACK)['Stacks'][0]
    previous = next(p['ParameterValue'] for p in stack['Parameters'] if p['ParameterKey'] == 'Image')
    record.update(account=ACCOUNT, region=REGION, previous_image=previous, status='PREPARING')
    save(record)
    if rollback:
        digest = validate_digest(rollback)
        details = ecr.describe_images(repositoryName=REPO, imageIds=[{'imageDigest': digest}])['imageDetails'][0]
        versions = [tag for tag in details.get('imageTags', []) if re.fullmatch(r'core-[a-f0-9]{12}-[a-f0-9]{16}', tag)]
        if len(versions) != 1:
            raise ValueError('Rollback image must have exactly one CORE source-version tag')
        record['version'] = versions[0]
    else:
        digest = build_image(session, config, record)
    image = f'{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{REPO}@{validate_digest(digest)}'
    record['image'] = image
    save(record)

    if image != previous:
        print(f"Deploying new image to ECS: {image}", flush=True)
        current_td = ecs.describe_task_definition(taskDefinition='archreactor-simulator')['taskDefinition']
        containers = list(current_td['containerDefinitions'])
        for c in containers:
            if c['name'] == 'core':
                c['image'] = image

        reg_kwargs = {
            'family': current_td['family'],
            'executionRoleArn': current_td['executionRoleArn'],
            'networkMode': current_td['networkMode'],
            'containerDefinitions': containers,
            'requiresCompatibilities': current_td['requiresCompatibilities'],
            'cpu': current_td['cpu'],
            'memory': current_td['memory'],
        }
        if 'runtimePlatform' in current_td:
            reg_kwargs['runtimePlatform'] = current_td['runtimePlatform']
        if 'taskRoleArn' in current_td:
            reg_kwargs['taskRoleArn'] = current_td['taskRoleArn']

        new_td = ecs.register_task_definition(**reg_kwargs)['taskDefinition']
        new_td_arn = new_td['taskDefinitionArn']
        print(f"Registered new TaskDef: {new_td_arn}", flush=True)

        print(f"Updating ECS service {SERVICE} to {new_td_arn}...", flush=True)
        ecs.update_service(cluster=SERVICE, service=SERVICE, taskDefinition=new_td_arn)
        record['status'] = 'UPDATE_IN_PROGRESS'
        record['task_definition'] = new_td_arn
        save(record)

    print("Waiting for ECS service deployment rollout to complete...", flush=True)
    try:
        service = wait_until(lambda: ecs.describe_services(cluster=SERVICE, services=[SERVICE])['services'][0],
                             lambda s: s['desiredCount'] > 0 and s['runningCount'] == s['desiredCount'] and len(s['deployments']) == 1 and s['deployments'][0].get('rolloutState') == 'COMPLETED',
                             lambda s: any(d.get('rolloutState') == 'FAILED' for d in s['deployments']), timeout=300)
    except Exception:
        diagnose_failure(ecs)
        raise
    tasks = list(ecs.get_paginator('list_tasks').paginate(cluster=SERVICE, serviceName=SERVICE).search('taskArns[]'))
    actual = ecs.describe_tasks(cluster=SERVICE, tasks=tasks) if tasks else {'tasks': [], 'failures': []}
    if actual.get('failures') or len(actual['tasks']) != service['desiredCount']:
        raise RuntimeError('Missing deployed tasks')
    for task in actual['tasks']:
        containers = [c for c in task['containers'] if c['name'] == 'core']
        if task.get('healthStatus') != 'HEALTHY' or task['taskDefinitionArn'] != service['taskDefinition'] or len(containers) != 1 or containers[0].get('imageDigest') != digest:
            raise RuntimeError('Deployed CORE image or gRPC health mismatch')
    record.update(status='HEALTHY', task_definition=service['taskDefinition'])
    save(record)
    print("Deployment complete and verified healthy:", json.dumps(record), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--github-actions', action='store_true', help='Use OIDC environment credentials in the allowed workflow only')
    parser.add_argument('--rollback', help='Deploy a previous verified sha256 digest without building')
    args = parser.parse_args()
    record = {}
    try:
        if args.rollback:
            validate_digest(args.rollback)
        deploy(make_session(args.github_actions), args.rollback, record)
    except Exception:
        if record:
            record['status'] = 'FAILED'
            save(record)
        raise


if __name__ == '__main__':
    main()
