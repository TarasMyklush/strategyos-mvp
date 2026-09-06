import pytest

from strategyos_mvp import board_api, board_memory, claim_store


PRINCIPAL = {'tenant_id': 'tenant-a', 'subject': 'ceo', 'role': 'executive'}


@pytest.mark.parametrize('purpose', ['executive_briefing', 'export'])
@pytest.mark.parametrize('reasons,allowed', [
    ([], True),
    (['bulk_revised_inputs_require_recompute'], True),
    (['bulk_withdrawn_evidence'], False),
    (['source_role_denied'], False),
    (['source_export_denied'], False),
    (['bulk_revised_inputs_require_recompute', 'source_export_denied'], False),
    (['bulk_revised_inputs_require_recompute', 'source_purpose_denied'], False),
])
def test_board_history_preserves_values_but_not_revoked_rights(monkeypatch, purpose, reasons, allowed):
    class Repository:
        def run_source_access(self, run, *, context):
            assert run == 'original-run'
            assert context.tenant_id == 'tenant-a'
            assert context.roles == frozenset({'executive'})
            assert context.purpose == purpose
            return {'allowed': not reasons, 'reasons': reasons}
    monkeypatch.setattr(claim_store, 'ClaimRepository', Repository)
    if allowed:
        board_memory.authorize_run('tenant-a', 'original-run', principal=PRINCIPAL, purpose=purpose)
    else:
        with pytest.raises(PermissionError):
            board_memory.authorize_run('tenant-a', 'original-run', principal=PRINCIPAL, purpose=purpose)


def test_board_policy_unavailable_or_foreign_tenant_fails_closed(monkeypatch):
    class Repository:
        def run_source_access(self, *args, **kwargs):
            raise RuntimeError('offline')
    monkeypatch.setattr(claim_store, 'ClaimRepository', Repository)
    for tenant in ('tenant-a', 'foreign'):
        with pytest.raises(PermissionError):
            board_memory.authorize_run(tenant, 'original-run', principal=PRINCIPAL)


def test_download_requests_export_not_ordinary_read_authority(monkeypatch):
    def denied(tenant, meeting, *, principal, purpose):
        assert principal == PRINCIPAL
        assert purpose == 'export'
        raise PermissionError('denied')
    monkeypatch.setattr(board_memory, 'read_meeting', denied)
    with pytest.raises(PermissionError):
        board_api.download('meeting', 'board.pdf', principal=PRINCIPAL)


def test_questions_reauthorize_even_though_they_are_post_requests(monkeypatch):
    def denied(tenant, meeting, *, principal, purpose):
        assert principal == PRINCIPAL
        assert purpose == 'executive_briefing'
        raise PermissionError('denied')
    monkeypatch.setattr(board_memory, 'read_meeting', denied)
    monkeypatch.setattr(board_memory, 'answer_from_snapshot', lambda *args: pytest.fail('Answered denied data'))
    with pytest.raises(PermissionError):
        board_api.question('meeting', board_api.BoardQuestion(question='Revenue?'), principal=PRINCIPAL)
