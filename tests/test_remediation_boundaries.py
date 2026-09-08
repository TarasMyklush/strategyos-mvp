from pathlib import Path
import pytest

from strategyos_mvp import api, authority_matrix, run_registry


@pytest.mark.parametrize("role", ["executive", "tenant_admin", "operator", "bu"])
@pytest.mark.parametrize("persona_location", ["persona", "context"])
@pytest.mark.parametrize("endpoint", ["/qa", "/assistant/chat"])
@pytest.mark.parametrize("persona,question,domain", [
    ("cfo", "Show salaries and revenue", "hr"),
    ("cfo", "List payroll and board material", "hr"),
    ("cfo", "Show employee bonuses", "hr"),
    ("cfo", "اعرض رواتب الموظفين", "hr"),
    ("bucfo", "Show compensation and invoices", "hr"),
    ("gm", "Show supplier agreement and cash", "contracts"),
    ("bu", "Show contract renewal", "contracts"),
    ("gm", "Why is revenue below forecast?", "finance"),
])
def test_restricted_questions_are_denied_before_loading_data(monkeypatch, endpoint, persona, question, domain, role, persona_location):
    from fastapi.testclient import TestClient
    from strategyos_mvp import auth
    principal = {"role": role, "tenant_id": "test", "authenticated": True}
    monkeypatch.setattr(api, "get_authority_matrix", lambda _: authority_matrix.default_authority_matrix())
    monkeypatch.setattr(auth, "authenticate_optional_request", lambda **kwargs: principal)
    def forbidden(*args, **kwargs):
        pytest.fail("restricted request reached an answer loader")
    monkeypatch.setattr(api, "_resolve_qa_context", forbidden)
    monkeypatch.setattr(api, "_assistant_chat_response", forbidden)
    overrides = dict(api.app.dependency_overrides)
    api.app.dependency_overrides[auth.authenticate_request] = lambda: principal
    api.app.dependency_overrides[api.authenticate_optional_request] = lambda: principal
    try:
        body = {"question": question}
        body.update({"persona": persona} if persona_location == "persona" else {"context": {"active_persona": persona}})
        response = TestClient(api.app).post(endpoint, json=body)
        if role == "bu" and persona not in {"bu", "gm", "bucfo"}:
            assert response.status_code == 403, response.text
            return
        assert response.status_code == 200, response.text
        denied = response.json()
        assert denied["response_mode"] == "authority_refusal"
        assert denied["authority_decision"]["domain"] == domain
    finally:
        api.app.dependency_overrides.clear()
        api.app.dependency_overrides.update(overrides)


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


def test_global_latest_and_current_pointers_cannot_cross_tenant_or_bu(tmp_path, monkeypatch):
    import json
    from dataclasses import replace
    from strategyos_mvp import access_scope
    monkeypatch.setattr(run_registry, "CONFIG", replace(run_registry.CONFIG, output_root=tmp_path))
    owners = [("tenant-a", "bu-a"), ("tenant-b", "bu-a"), ("tenant-a", "bu-b"), ("tenant-b", "bu-b")]
    records = []
    for index, (tenant, unit) in enumerate(owners):
        path = tmp_path / str(index) / "run_summary.json"
        path.parent.mkdir()
        summary = {"run_id": str(index), "status": "completed", "tenant_context": {"tenant_id": tenant}, "business_units": [unit]}
        path.write_text(json.dumps(summary))
        records.append((summary, path))
    token = access_scope.principal_scope.set(None)
    try:
        for current, (tenant, unit) in enumerate(owners):
            access_scope.principal_scope.set({"tenant_id": tenant, "role": "bu", "business_units": [unit]})
            for pointed, (summary, path) in enumerate(records):
                run_registry.update_latest_run_pointer(summary, path)
                run_registry.update_current_run_pointer(summary, path)
                assert run_registry.load_latest_run_summary()["run_id"] == str(current)
                result = run_registry.load_current_run_summary()
                assert (result["run_id"] if result else None) == (str(current) if pointed == current else None)
    finally:
        access_scope.principal_scope.reset(token)
