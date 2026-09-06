import pytest
from fastapi import HTTPException
from strategyos_mvp import claim_api,claim_priority


def test_priority_endpoint_requires_tenant_admin_and_maps_stale_version(monkeypatch):
    route=next(r for r in claim_api.router.routes if getattr(r,'path',None)=='/api/claims/priority-policies')
    for role in ['executive','operator']:
        with pytest.raises(HTTPException) as denied:
            route.dependant.dependencies[0].call(principal={'role':role})
        assert denied.value.status_code==403
    request=claim_priority.PriorityDecision(reference_revision_id='11111111-1111-1111-1111-111111111111',
        ranked_source_keys=['source'],required_assessment=None,expected_policy_version=0,rationale='Explicit decision')
    # The application's shared role hierarchy admits system identities. The
    # priority execution invariant is deliberately stricter than that hierarchy.
    with pytest.raises(HTTPException) as system_denied:
        claim_api.record_source_priority(request,{'role':'system','subject':'service','tenant_id':'tenant'})
    assert system_denied.value.status_code==403
    def conflict(*args,**kwargs):
        assert kwargs['context'].principal_id=='authenticated-admin'
        assert kwargs['context'].tenant_id=='tenant'
        raise claim_priority.PriorityConflict('Policy changed')
    monkeypatch.setattr(claim_priority,'record_priority',conflict)
    with pytest.raises(HTTPException) as error:
        claim_api.record_source_priority(request,{'role':'tenant_admin','subject':'authenticated-admin','tenant_id':'tenant'})
    assert error.value.status_code==409
