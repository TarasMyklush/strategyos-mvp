from types import SimpleNamespace

import pytest

from strategyos_mvp import access_scope, api, claim_store, config
from strategyos_mvp.twins import source_scope


@pytest.fixture
def scoped_runtime(monkeypatch):
    monkeypatch.setattr(config,'load_config',lambda:SimpleNamespace(api_auth_enabled=True,tenant_slug='tenant-a'))
    monkeypatch.setattr(api,'_latest_summary',lambda:{'run_id':'run-one'})
    monkeypatch.setattr(api,'_summary_with_governed_claim_snapshot',lambda summary,**kwargs:{**summary,'canonical_claim_status':'ready'})
    class Repository:
        def resolve_context(self, context): return context
        def run_source_access(self, run, *, context):
            assert run=='run-one'
            return {'allowed':True}
    monkeypatch.setattr(claim_store,'ClaimRepository',Repository)
    token = access_scope.principal_scope.set({'tenant_id':'tenant-a','subject':'ceo','role':'executive'})
    binding = source_scope.bound_surface.set(None)
    yield
    source_scope.bound_surface.reset(binding)
    access_scope.principal_scope.reset(token)


def test_authenticated_twin_state_never_reads_legacy_or_other_actor_directory(scoped_runtime,tmp_path):
    first = source_scope.scoped_directory(tmp_path)
    assert first.parent == tmp_path/'governed-v1'
    assert len(first.name)==64
    actor = access_scope.principal_scope.get()
    for change in ({'tenant_id':'tenant-b'}, {'subject':'cfo'}, {'role':'tenant_admin'}):
        token = access_scope.principal_scope.set({**actor,**change})
        try:
            assert source_scope.scoped_directory(tmp_path)!=first
        finally:
            access_scope.principal_scope.reset(token)


@pytest.mark.parametrize('state',['missing','denied','revised','unavailable'])
def test_no_saved_state_directory_on_missing_or_revoked_source_authority(scoped_runtime,monkeypatch,tmp_path,state):
    class Repository:
        def resolve_context(self, context): return context
        def run_source_access(self,run,*,context):
            if state=='unavailable': raise RuntimeError('offline')
            return {'allowed':False,'reasons':['bulk_revised_inputs_require_recompute'] if state=='revised' else ['source_role_denied']}
    monkeypatch.setattr(claim_store,'ClaimRepository',Repository)
    if state=='missing': monkeypatch.setattr(api,'_latest_summary',lambda:None)
    with pytest.raises(PermissionError): source_scope.scoped_directory(tmp_path)
    assert list(tmp_path.iterdir())==[]


def test_one_request_retains_its_authorized_run_and_next_request_rechecks(scoped_runtime,monkeypatch,tmp_path):
    first = source_scope.scoped_directory(tmp_path)
    monkeypatch.setattr(api,'_latest_summary',lambda:pytest.fail('Changed data mid-request'))
    assert source_scope.scoped_directory(tmp_path)==first
    source_scope.bound_surface.set(None)
    monkeypatch.setattr(api,'_latest_summary',lambda:None)
    with pytest.raises(PermissionError): source_scope.scoped_directory(tmp_path)


def test_background_runtime_does_not_inherit_interactive_identity(scoped_runtime,monkeypatch,tmp_path):
    token = access_scope.principal_scope.set(None)
    monkeypatch.setattr(claim_store,'ClaimRepository',lambda:pytest.fail('Invented background authority'))
    try:
        with pytest.raises(PermissionError): source_scope.scoped_directory(tmp_path)
    finally:
        access_scope.principal_scope.reset(token)


def test_readiness_does_not_read_business_inboxes(monkeypatch):
    from strategyos_mvp.twins import tools, api as twin_api
    monkeypatch.setattr(tools,'build_app_repositories',lambda:pytest.fail('Readiness read private work'))
    result = twin_api.twin_operational_health_payload()
    assert result['diagnostics']=={}
    assert result['diagnostics_status']=='not_inspected_without_source_scope'


def test_empty_execution_is_not_reported_as_no_business_attention():
    from pathlib import Path
    text = Path(api.__file__).read_text()
    assert 'No execution is recorded for this actor and analysis yet.' in text
    assert 'Business priorities remain in Decisions for you.' in text
    assert 'Nothing in the leadership-team workflow requires your attention.' not in text


@pytest.mark.parametrize('failure', [PermissionError('private reason'), api.HTTPException(503, 'private reason')])
def test_optional_activity_denial_is_unknown_not_zero(monkeypatch, failure):
    def denied(): raise failure
    monkeypatch.setattr(api, 'build_app_repositories', denied)
    result = api._agents_surface_payload(None, {'authenticated': True})
    assert result['status'] == 'unavailable'
    assert result['summary'] == {}
    assert result['digital_twins'] == []
    assert 'private reason' not in str(result)
    assert result['activity']['metrics'] == []


def test_hermes_does_not_invent_activity_when_source_scope_is_unavailable(monkeypatch):
    def denied(): raise PermissionError('private reason')
    monkeypatch.setattr(api, 'build_app_repositories', denied)
    result = api._resolve_digital_twin_status('What is Atlas doing now?', summary=None,
        role='executive', public_safe=False)
    assert result['matched'] is True
    assert 'unavailable' in result['answer']
    assert result['citations'] == []
    assert 'no issue' not in result['answer'].lower()


@pytest.mark.parametrize('method', ['submit_scheduled_cycle','submit_event_execution',
    'execute_scheduled_cycle_job','execute_event_execution_job'])
def test_disabled_jobs_do_not_open_legacy_state(monkeypatch,method):
    from strategyos_mvp.twins import execution
    monkeypatch.setattr(execution,'build_app_repositories',lambda:pytest.fail('Disabled job opened state'))
    config = SimpleNamespace(twins_enabled=True,twins_scheduler_enabled=False)
    args = {'cycle_type':'daily'} if 'scheduled' in method else {}
    result = getattr(execution,method)(config=config,**args)
    assert result['status']=='disabled'
