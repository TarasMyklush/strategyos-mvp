from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import strategyos_mvp.authority_matrix as authority_module
from strategyos_mvp.api import app
from strategyos_mvp.agent_runtime import tools as agent_tools
from strategyos_mvp.agent_runtime.tools import ToolExecutionContext, ToolInputInvalid


@pytest.fixture()
def authority_store(tmp_path, monkeypatch):
    monkeypatch.setenv("STRATEGYOS_AUTHORITY_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(authority_module, "database_connection", lambda: (None, {"reason": "test fallback"}))
    return tmp_path


def test_matrix_is_versioned_durable_and_audited(authority_store) -> None:
    original = authority_module.get_authority_matrix("tenant-a")
    original["subjects"][0]["rights"]["finance"] = "recommend"
    saved = authority_module.save_authority_matrix(
        "tenant-a", original, actor="ceo@example.test", expected_version=1
    )

    assert saved["version"] == 2
    assert authority_module.get_authority_matrix("tenant-a")["subjects"][0]["rights"]["finance"] == "recommend"
    audit = authority_store / "tenant-a.audit.jsonl"
    entry = json.loads(audit.read_text(encoding="utf-8").splitlines()[-1])
    assert entry["actor"] == "ceo@example.test"
    assert entry["version"] == 2

    with pytest.raises(ValueError, match="changed since"):
        authority_module.save_authority_matrix(
            "tenant-a", original, actor="stale-editor", expected_version=1
        )


def test_assistant_refuses_before_answer_and_cites_exact_matrix_row(authority_store) -> None:
    client = TestClient(app)
    response = client.post(
        "/assistant/chat",
        json={"persona": "gm", "question": "Why is revenue below forecast?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["response_mode"] == "authority_refusal"
    assert payload["authority_decision"]["subject_id"] == "assistant:iris"
    assert payload["authority_decision"]["resolved_right"] == "view"
    assert payload["authority_decision"]["required_right"] == "analyse"
    assert "§3, assistant:iris × finance" in payload["answer"]


def test_authority_api_round_trip_uses_optimistic_version(authority_store) -> None:
    client = TestClient(app)
    current = client.get("/authority-matrix").json()
    assert current["editable"] is True
    matrix = current["matrix"]
    matrix["subjects"][0]["rights"]["finance"] = "recommend"

    saved = client.put(
        "/authority-matrix",
        json={"matrix": matrix, "expected_version": matrix["version"]},
    )
    assert saved.status_code == 200
    assert saved.json()["matrix"]["version"] == 2
    assert client.get("/authority-matrix").json()["matrix"]["subjects"][0]["rights"]["finance"] == "recommend"

    stale = client.put(
        "/authority-matrix",
        json={"matrix": matrix, "expected_version": 1},
    )
    assert stale.status_code == 409


def test_agent_tool_is_denied_before_handler_executes(authority_store, monkeypatch) -> None:
    matrix = authority_module.get_authority_matrix("tenant-agent")
    subject = next(item for item in matrix["subjects"] if item["id"] == "agent:cash-recovery")
    subject["rights"]["finance"] = "none"
    authority_module.save_authority_matrix("tenant-agent", matrix, actor="cio", expected_version=1)
    called = False

    def forbidden_handler(ctx, input_payload):
        nonlocal called
        called = True
        return {"unexpected": True}

    monkeypatch.setitem(agent_tools.TOOL_HANDLERS, "findings.read", forbidden_handler)
    context = ToolExecutionContext(
        tenant_id="tenant-agent",
        task_id="task-1",
        run_id="run-1",
        authority_subject_id="agent:cash-recovery",
    )
    with pytest.raises(ToolInputInvalid, match=r"Authority Matrix §3, agent:cash-recovery × finance"):
        agent_tools.invoke_tool("findings.read", context, {})
    assert called is False


def test_default_store_uses_writable_workspace_root(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("STRATEGYOS_AUTHORITY_DATA_DIR", raising=False)
    monkeypatch.setenv("STRATEGYOS_WORKSPACE_ROOT", str(tmp_path))
    assert authority_module._data_root() == tmp_path / ".strategyos_mvp_data" / "authority"


@pytest.mark.parametrize("first,second", [("tenant/a", "tenant-a"), ("tenant:a", "tenant/a"), ("a" * 121, "a" * 120 + "b")])
def test_file_policy_keys_do_not_alias_tenants(authority_store, first, second):
    assert authority_module._file_path(first) != authority_module._file_path(second)
    matrix = authority_module.default_authority_matrix()
    matrix["subjects"][0]["rights"]["finance"] = "none"
    authority_module.save_authority_matrix(first, matrix, actor="test", expected_version=1)
    assert authority_module.get_authority_matrix(first)["subjects"][0]["rights"]["finance"] == "none"
    assert authority_module.get_authority_matrix(second)["subjects"][0]["rights"]["finance"] == "analyse"


@pytest.mark.parametrize("content", ["{broken", "[]", '{"subjects": []}'])
def test_invalid_saved_policy_never_restores_default_permissions(authority_store, content):
    (authority_store / "tenant-a.json").write_text(content)
    with pytest.raises(RuntimeError, match="access remains closed"):
        authority_module.get_authority_matrix("tenant-a")


def test_ambiguous_legacy_policy_requires_verified_owner(authority_store):
    (authority_store / "tenant-a.json").write_text(json.dumps(authority_module.default_authority_matrix()))
    with pytest.raises(RuntimeError, match="owner-verified migration"):
        authority_module.get_authority_matrix("tenant/a")


@pytest.mark.parametrize("endpoint", ["/qa", "/assistant/chat"])
def test_unreadable_policy_returns_service_unavailable_before_loading(authority_store, monkeypatch, endpoint):
    from strategyos_mvp import api
    def unavailable(tenant):
        raise authority_module.AuthorityPolicyUnavailable("Saved authority policy is unreadable")
    def forbidden(*args, **kwargs):
        pytest.fail("An unavailable policy must not reach an answer loader")
    monkeypatch.setattr(api, "get_authority_matrix", unavailable)
    monkeypatch.setattr(api, "_resolve_qa_context", forbidden)
    monkeypatch.setattr(api, "_assistant_chat_response", forbidden)
    response = TestClient(app).post(endpoint, json={"persona": "ceo", "question": "Show revenue"})
    assert response.status_code == 503
    assert "Access remains closed" in response.json()["detail"]
