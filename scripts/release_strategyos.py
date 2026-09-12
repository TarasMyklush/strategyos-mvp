#!/usr/bin/env python3
"""One supervised, sequential StrategyOS release. Default is a read-only plan."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time

CI = 'strategyos-ci.yml'
DEPLOY = 'strategyos-deploy.yml'
REPO = 'TarasMyklush/strategyos-mvp'


class ReleaseBlocked(RuntimeError):
    pass


class GitHub:
    run_factual_corpus = False

    def api(self, path, payload=None):
        command = ['gh', 'api', f'repos/{REPO}/{path}']
        if payload is not None:
            command += ['--method', 'POST', '--input', '-']
        result = subprocess.run(command, input=json.dumps(payload) if payload is not None else None,
                                capture_output=True, text=True, check=True)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def sha(self, ref):
        from urllib.parse import quote
        return self.api('commits/' + quote(ref, safe=''))['sha']

    def active(self):
        found = {}
        for status in ('queued', 'in_progress', 'waiting', 'pending', 'requested'):
            for run in self.api(f'actions/runs?status={status}&per_page=100')['workflow_runs']:
                found[run['id']] = run
        return list(found.values())

    def runs(self, workflow, sha):
        return self.api(f'actions/workflows/{workflow}/runs?head_sha={sha}&per_page=100')['workflow_runs']

    def dispatch(self, workflow, ref, sha):
        prior = {r['id'] for r in self.runs(workflow, sha)}
        payload = {'ref': ref}
        if workflow == DEPLOY:
            payload['inputs'] = {
                'target_environment':'hetzner-qa',
                'run_smoke':'false',
                'run_factual_corpus':'true' if self.run_factual_corpus else 'false',
            }
        self.api(f'actions/workflows/{workflow}/dispatches', payload)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            fresh = [r for r in self.runs(workflow, sha) if r['id'] not in prior]
            if len(fresh) == 1:
                return fresh[0]['id']
            if len(fresh) > 1:
                raise ReleaseBlocked('Multiple new runs detected. Inspect Actions; no further dispatch is allowed.')
            time.sleep(5)
        raise ReleaseBlocked('Dispatch receipt is uncertain. Inspect Actions; do not dispatch again.')

    def wait(self, identity):
        deadline = time.monotonic() + 3600
        while time.monotonic() < deadline:
            run = self.api(f'actions/runs/{identity}')
            if run['status'] == 'completed':
                return run
            time.sleep(10)
        raise ReleaseBlocked('Run is still active. Inspect Actions; no replacement was dispatched.')


def idle(github):
    active = github.active()
    if active:
        raise ReleaseBlocked('A workflow is already active; no run started: ' + ', '.join(str(r['id']) for r in active))


def release(github, ref, execute=False):
    idle(github)
    sha = github.sha(ref)
    deployments = github.runs(DEPLOY, sha)
    if any(r.get('conclusion') == 'success' for r in deployments):
        return {'status':'already_accepted', 'sha':sha, 'dispatched':[],
                'note':'A successful deployment acceptance exists for this commit; no duplicate was started. This does not independently attest the current server.'}
    ci = github.runs(CI, sha)
    # Match the deployment gate, which checks the latest CI attempt for this SHA.
    green = bool(ci) and ci[0].get('conclusion') == 'success'
    if not green and ci:
        raise ReleaseBlocked('CI already attempted this commit without success. Resolve the failure; no automatic retry.')
    if deployments:
        raise ReleaseBlocked('Deployment already attempted this commit. Investigate before explicitly retrying; no automatic retry.')
    if not execute:
        return {'status':'plan', 'sha':sha, 'steps':([CI] if not green else []) + [DEPLOY],
                'note':'Sequential execution only; existing exact-commit CI is reused.'}
    dispatched = []
    for workflow in ([CI] if not green else []) + [DEPLOY]:
        idle(github)
        if github.sha(ref) != sha:
            raise ReleaseBlocked('Branch moved after validation. No further workflow was dispatched.')
        identity = github.dispatch(workflow, ref, sha)
        dispatched.append(identity)
        print(json.dumps({'workflow':workflow,'run_id':identity,'status':'waiting'}), flush=True)
        result = github.wait(identity)
        if result.get('head_sha') != sha or result.get('conclusion') != 'success':
            raise ReleaseBlocked(f'Run {identity} did not pass for the expected commit. No further workflow was dispatched.')
    return {'status':'accepted','sha':sha,'dispatched':dispatched}


@contextmanager
def local_lock():
    path = Path(tempfile.gettempdir()) / ('strategyos-release-' + hashlib.sha256(REPO.encode()).hexdigest()[:12] + '.lock')
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ReleaseBlocked('Another release command is already running on this host.') from None
        yield


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', required=True)
    parser.add_argument('--execute', action='store_true', help='Run the reviewed plan sequentially; otherwise read only.')
    parser.add_argument('--full-factual-gate', action='store_true',
                        help='Collect the fixed 50-question corpus after the hosted smoke suite.')
    args = parser.parse_args()
    try:
        with local_lock():
            github = GitHub()
            github.run_factual_corpus = args.full_factual_gate
            print(json.dumps(release(github, args.ref, args.execute)))
    except (ReleaseBlocked, subprocess.CalledProcessError) as exc:
        print(json.dumps({'status':'blocked','reason':str(exc)}))
        raise SystemExit(1)
