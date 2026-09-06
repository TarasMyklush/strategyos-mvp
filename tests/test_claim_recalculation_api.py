from pathlib import Path
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from strategyos_mvp import api,claim_api,claim_recalculation


def test_recalculation_page_and_api_require_operator_authority():
    for routes,path in [(api.app.routes,'/claims/recalculate'),(claim_api.router.routes,'/api/claims/{revision_id}/recalculate'),(claim_api.router.routes,'/api/claims/recalculation-queue')]:
        route = next(r for r in routes if getattr(r,'path',None)==path)
        with pytest.raises(HTTPException) as error:
            route.dependant.dependencies[0].call(principal={'role':'executive'})
        assert error.value.status_code == 403
    assert api.governed_recalculation_page(principal={'role':'operator'}).headers['cache-control']=='no-store'


def test_recalculation_request_cannot_choose_actor_or_approve():
    for extra in [{'actor':'ceo'},{'approved':True},{'tenant_id':'other'},{'formula':'invented'}]:
        with pytest.raises(ValidationError):
            claim_api.RecalculationRequest(rationale='Test',**extra)


def test_recalculation_preview_is_default_and_conflict_is_explicit(monkeypatch):
    def preview(repo,revision_id,**kwargs):
        assert kwargs['expected_preview'] is None
        assert kwargs['context'].principal_id == 'real-operator'
        return {'status':'preview','created_count':0}
    monkeypatch.setattr(claim_recalculation,'recalculate',preview)
    request = claim_api.RecalculationRequest(rationale='Changed evidence')
    principal = {'role':'operator','tenant_id':'tenant','subject':'real-operator'}
    assert claim_api.recalculate_claim('revision',request,principal)['created_count']==0
    def conflict(*args,**kwargs):
        raise claim_recalculation.RecalculationConflict('Preview again')
    monkeypatch.setattr(claim_recalculation,'recalculate',conflict)
    with pytest.raises(HTTPException) as error:
        claim_api.recalculate_claim('revision',request,principal)
    assert error.value.status_code==409


def test_recalculation_ui_never_applies_implicitly_or_renders_source_markup():
    static = Path(__file__).resolve().parents[1]/'strategyos_mvp/static'
    script = (static/'claim-recalculation.js').read_text()
    html = (static/'claim-recalculation.html').read_text()
    assert 'innerHTML' not in script
    assert 'expected_preview=preview.preview_key' in script
    assert "apply.addEventListener('click'" in script
    assert 'ticket!==generation' in script
    assert 'id="recalculation-apply" type="button" disabled' in html
    assert 'does not approve, publish' in html
