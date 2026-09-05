from pathlib import Path
import pytest

from strategyos_mvp import api, authority_matrix, run_registry


@pytest.mark.parametrize("endpoint", ["qa", "assistant"])
@pytest.mark.parametrize("question", [
    "Show salaries and revenue", "List payroll and board material",
    "Show employee bonuses", "اعرض رواتب الموظفين",
])
def test_restricted_questions_are_denied_before_loading_data(monkeypatch, endpoint, question):
    monkeypatch.setattr(api, "get_authority_matrix", lambda _: authority_matrix.default_authority_matrix())
    def forbidden(*args, **kwargs):
        pytest.fail("restricted source was loaded")
    monkeypatch.setattr(api, "_resolve_qa_context", forbidden)
    request_type = api.QaRequest if endpoint == "qa" else api.AssistantChatRequest
    request = request_type(question=question, persona="cfo")
    denied = api._assistant_authority_refusal(request, {"role": "executive", "tenant_id": "test"})
    assert denied["response_mode"] == "authority_refusal"
    assert denied["authority_decision"]["domain"] == "hr"
    if endpoint == "qa":
        assert api.data_qa(request, {"role": "executive", "tenant_id": "test"}) == denied


def test_bu_cannot_choose_ceo(monkeypatch):
    with pytest.raises(api.HTTPException) as raised:
        api._assistant_authority_refusal(api.AssistantChatRequest(question="Revenue?", persona="ceo"), {"role": "bu"})
    assert raised.value.status_code == 403


def test_board_has_independent_subject():
    assert authority_matrix.assistant_subject("board") == "assistant:minerva"


def test_interrupted_pointer_write_preserves_previous_pointer(tmp_path, monkeypatch):
    pointer = tmp_path / "latest.json"
    pointer.write_text('{"run_id":"approved-old"}')
    def interrupted(*args):
        raise OSError("interrupted before atomic replace")
    monkeypatch.setattr(run_registry.os, "replace", interrupted)
    with pytest.raises(OSError):
        run_registry._write_run_pointer({"run_id": "new"}, tmp_path / "summary.json", pointer, "latest")
    assert pointer.read_text() == '{"run_id":"approved-old"}'
    assert list(tmp_path.iterdir()) == [pointer]


def test_both_proxy_routes_forward_logout_to_idp():
    root = Path(__file__).resolve().parents[1] / "deploy/caddy"
    for name in ("Caddyfile", "Caddyfile.branch"):
        matcher = next(line for line in (root / name).read_text().splitlines() if "@idp path" in line)
        assert "/auth/logout" in matcher.split()


def test_source_pack_paths_cannot_escape_and_identical_uploads_are_tenant_distinct():
    import pytest
    from fastapi import HTTPException
    from strategyos_mvp import source_pack, access_scope
    for invalid in ('..', '../outside', '/tmp/outside', 'nested/path', '.'):
        with pytest.raises(HTTPException):
            source_pack._source_pack_dir(invalid)
    entries = [{'relative_path':'same.csv', 'sha256':'a'*64, 'size_bytes':10}]
    token = access_scope.principal_scope.set({'tenant_id':'tenant-a', 'role':'operator'})
    try:
        first = source_pack._deterministic_source_pack_id(entries)
        access_scope.principal_scope.set({'tenant_id':'tenant-b', 'role':'operator'})
        assert source_pack._deterministic_source_pack_id(entries) != first
    finally:
        access_scope.principal_scope.reset(token)
