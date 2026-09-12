import importlib.util
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('release_strategyos',Path(__file__).parents[1]/'scripts/release_strategyos.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class Host:
    def __init__(self):
        self.running=[];self.history={m.CI:[],m.DEPLOY:[]};self.calls=[];self.ref='abc';self.result='success';self.moves=False
    def active(self): return self.running
    def sha(self,ref): return self.ref
    def runs(self,w,sha): return self.history[w]
    def dispatch(self,w,ref,sha):
        assert not self.running
        self.calls.append(w);self.running=[{'id':len(self.calls)}];return len(self.calls)
    def wait(self,i):
        self.running=[]
        if self.moves:self.ref='changed'
        return {'head_sha':'abc','conclusion':self.result}


def test_read_only_plan_starts_nothing():
    h=Host();assert m.release(h,'branch')['steps']==[m.CI,m.DEPLOY];assert not h.calls


def test_ci_finishes_before_deployment_starts():
    h=Host();assert m.release(h,'branch',True)['status']=='accepted';assert h.calls==[m.CI,m.DEPLOY]


def test_exact_commit_ci_is_reused():
    h=Host();h.history[m.CI]=[{'conclusion':'success'}]
    m.release(h,'branch',True);assert h.calls==[m.DEPLOY]


def test_accepted_commit_does_not_redeploy():
    h=Host();h.history[m.DEPLOY]=[{'conclusion':'success'}]
    assert m.release(h,'branch',True)['status']=='already_accepted';assert not h.calls


@pytest.mark.parametrize('status',['failure','cancelled','timed_out'])
def test_failed_ci_never_dispatches_deployment(status):
    h=Host();h.result=status
    with pytest.raises(m.ReleaseBlocked):m.release(h,'branch',True)
    assert h.calls==[m.CI]


def test_branch_movement_between_ci_and_deploy_stops_release():
    h=Host();h.moves=True
    with pytest.raises(m.ReleaseBlocked):m.release(h,'branch',True)
    assert h.calls==[m.CI]


def test_active_workflow_prevents_a_queue():
    h=Host();h.running=[{'id':42}]
    with pytest.raises(m.ReleaseBlocked):m.release(h,'branch',True)
    assert not h.calls


@pytest.mark.parametrize('workflow',[m.CI,m.DEPLOY])
def test_failed_attempt_does_not_automatically_retry(workflow):
    h=Host();h.history[workflow]=[{'conclusion':'failure'}]
    with pytest.raises(m.ReleaseBlocked):m.release(h,'branch',True)
    assert not h.calls
