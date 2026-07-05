"""Phase 9 tests for model reasoning and scheduled/event execution."""

from __future__ import annotations

import json
import os
from io import BytesIO
from urllib.error import HTTPError

from fastapi.testclient import TestClient

import strategyos_mvp.api as api_module
import strategyos_mvp.auth as auth_module
from strategyos_mvp.config import load_config
from strategyos_mvp.twins.execution import submit_event_execution, submit_scheduled_cycle
from strategyos_mvp.twins.memory import create_twin_state
from strategyos_mvp.twins.persona import CEO_TWIN
from strategyos_mvp.twins.runtime import TwinRuntime
from strategyos_mvp.twins.store import build_repositories


client = TestClient(api_module.app)


def _apply_env(env_updates: dict[str, str | None]):
    original = {key: os.environ.get(key) for key in env_updates}
    for key, value in env_updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    config = load_config()
    api_module.CONFIG = config
    auth_module.CONFIG = config
    return original


def _restore_env(original: dict[str, str | None]):
    for key, value in original.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    config = load_config()
    api_module.CONFIG = config
    auth_module.CONFIG = config


def test_deterministic_fallback_when_no_model_available(tmp_path, monkeypatch):
    original = _apply_env({
        "STRATEGYOS_TWINS_DATA_DIR": str(tmp_path / "app-data"),
        "STRATEGYOS_MODEL_PROVIDER_ENABLED": "false",
        "STRATEGYOS_LLM_CHAT_ENABLED": "false",
    })
    try:
        repositories = build_repositories(tmp_path / "twins")
        runtime = TwinRuntime(CEO_TWIN, create_twin_state("ceo"), repositories=repositories)

        summary = runtime.run_once()

        traces = repositories.reasoning.list("ceo")
        assert len(traces) == 2
        assert all(trace["source"] == "deterministic_fallback" for trace in traces)
        assert all(trace["fallback_reason"] for trace in traces)
        assert summary["cycle"] >= 1
        assert "reasoning_trace_ids" in summary
    finally:
        _restore_env(original)


def test_structured_reasoning_output_is_normalized_and_used(tmp_path, monkeypatch):
    original = _apply_env({
        "STRATEGYOS_TWINS_DATA_DIR": str(tmp_path / "app-data"),
        "STRATEGYOS_MODEL_PROVIDER_ENABLED": "true",
        "STRATEGYOS_LLM_CHAT_ENABLED": "true",
        "STRATEGYOS_RUN_POLICY": "external-approved",
        "STRATEGYOS_APPROVED_EXTERNAL_MODES": "model_provider_use",
        "STRATEGYOS_LLM_API_KEY": "test-key",
        "STRATEGYOS_LLM_BASE_URL": "https://litellm.local",
        "STRATEGYOS_LLM_MODEL": "gpt-4o-mini",
    })
    try:
        import strategyos_mvp.twins.reasoning as reasoning_module

        monkeypatch.setattr(reasoning_module.llm_qa, "chat_status", lambda config: {
            "enabled": True,
            "provider": "litellm",
            "model": "gpt-4o-mini",
        })

        def _fake_call(*, config, stage, input_context):
            if stage == "orient":
                return json.dumps({
                    "issues": [
                        {
                            "investigation_id": "ceo_issue_1",
                            "type": "kpi_gap",
                            "priority": "high",
                            "kpi_node_id": "margin_q2",
                            "detail": "Margin evidence is stale and needs finance refresh.",
                            "owner": "cfo",
                            "resolution_hint": "request_data",
                            "evidence_refs": [{"finding_id": "F-001"}],
                        }
                    ],
                    "summary": "Prioritized finance gap.",
                    "confidence": 0.82,
                    "review_state": "needs_review",
                    "citations": [{"finding_id": "F-001"}],
                })
            return json.dumps({
                "decisions": [
                    {
                        "investigation_id": "ceo_issue_1",
                        "action": "send_data_request",
                        "target_role": "cfo",
                        "reason": "Finance owns the stale margin evidence.",
                        "evidence_refs": [{"finding_id": "F-001"}],
                    }
                ],
                "summary": "Request fresh finance evidence.",
                "confidence": 0.77,
                "review_state": "needs_review",
                "citations": [{"finding_id": "F-001"}],
            })

        monkeypatch.setattr(reasoning_module, "_call_litellm_reasoning", _fake_call)

        repositories = build_repositories(tmp_path / "twins")
        runtime = TwinRuntime(CEO_TWIN, create_twin_state("ceo"), repositories=repositories)
        summary = runtime.run_once()

        assert any(action["action"] == "send_data_request" for action in summary["actions"])
        traces = repositories.reasoning.list("ceo")
        assert traces[0]["source"] == "litellm"
        assert traces[0]["output"]
        assert 0.0 <= traces[0]["confidence"] <= 1.0
    finally:
        _restore_env(original)


def test_reasoning_trace_persistence_captures_review_fields(tmp_path, monkeypatch):
    original = _apply_env({
        "STRATEGYOS_TWINS_DATA_DIR": str(tmp_path / "app-data"),
        "STRATEGYOS_MODEL_PROVIDER_ENABLED": "false",
        "STRATEGYOS_LLM_CHAT_ENABLED": "false",
    })
    try:
        repositories = build_repositories(tmp_path / "twins")
        runtime = TwinRuntime(CEO_TWIN, create_twin_state("ceo"), repositories=repositories)
        runtime.state.working_memory["last_query"] = "why is margin down"
        runtime.run_once()

        trace = repositories.reasoning.list("ceo")[-1]
        assert trace["input_context"]["role"] == "ceo"
        assert "run_context" in trace["input_context"]
        assert "evidence_refs" in trace
        assert "approval_disposition" in trace
        assert "review_state" in trace
    finally:
        _restore_env(original)


def test_scheduled_cycle_execution_runs_through_service_path(tmp_path):
    repositories = build_repositories(tmp_path / "twins")

    result = submit_scheduled_cycle("daily", repositories=repositories, config=load_config())

    assert result["status"] == "completed"
    assert result["cycle_type"] == "daily_standup"
    execution = repositories.execution.load(result["execution_id"])
    assert execution is not None
    assert execution["execution_type"] == "scheduled_cycle"
    assert execution["status"] == "completed"


def test_event_triggered_execution_runs_on_kpi_breach(tmp_path):
    repositories = build_repositories(tmp_path / "twins")
    repositories.kpis.save({
        "breach_margin": {
            "owner": "ceo",
            "value": 50.0,
            "threshold": 100.0,
            "status": "current",
            "last_updated": "2026-06-28T00:00:00+00:00",
        }
    })

    result = submit_event_execution(repositories=repositories, config=load_config())

    assert result["status"] == "completed"
    assert any(event["event_type"] == "kpi_breach" for event in result["events"])
    investigations = repositories.investigations.list("ceo")
    assert any(item["id"].startswith("auto-breach_margin") for item in investigations)


def test_model_guardrail_blocks_state_changing_actions(tmp_path, monkeypatch):
    original = _apply_env({
        "STRATEGYOS_TWINS_DATA_DIR": str(tmp_path / "app-data"),
        "STRATEGYOS_MODEL_PROVIDER_ENABLED": "true",
        "STRATEGYOS_LLM_CHAT_ENABLED": "true",
        "STRATEGYOS_RUN_POLICY": "external-approved",
        "STRATEGYOS_APPROVED_EXTERNAL_MODES": "model_provider_use",
        "STRATEGYOS_LLM_API_KEY": "test-key",
        "STRATEGYOS_LLM_BASE_URL": "https://litellm.local",
        "STRATEGYOS_LLM_MODEL": "gpt-4o-mini",
    })
    try:
        import strategyos_mvp.twins.reasoning as reasoning_module

        monkeypatch.setattr(reasoning_module.llm_qa, "chat_status", lambda config: {
            "enabled": True,
            "provider": "litellm",
            "model": "gpt-4o-mini",
        })

        def _fake_call(*, config, stage, input_context):
            if stage == "orient":
                return json.dumps({
                    "issues": [
                        {
                            "investigation_id": "ceo_issue_1",
                            "type": "kpi_gap",
                            "priority": "high",
                            "kpi_node_id": "margin_q2",
                            "detail": "Escalate the target reset.",
                            "owner": "ceo",
                            "resolution_hint": "escalate",
                        }
                    ],
                    "summary": "Needs escalation.",
                    "confidence": 0.9,
                    "review_state": "needs_review",
                    "citations": [],
                })
            return json.dumps({
                "decisions": [
                    {
                        "investigation_id": "ceo_issue_1",
                        "action": "redirect",
                        "target_role": "cfo",
                        "reason": "Send ownership to finance immediately.",
                    }
                ],
                "summary": "Redirect to finance.",
                "confidence": 0.88,
                "review_state": "needs_review",
                "citations": [],
            })

        monkeypatch.setattr(reasoning_module, "_call_litellm_reasoning", _fake_call)

        repositories = build_repositories(tmp_path / "twins")
        runtime = TwinRuntime(CEO_TWIN, create_twin_state("ceo"), repositories=repositories)
        summary = runtime.run_once()

        assert any(action["action"] == "request_human_review" for action in summary["actions"])
        decisions = repositories.governance.list_decisions("ceo")
        assert any(item["event_type"] == "reasoning_guardrail" for item in decisions)
        traces = repositories.reasoning.list("ceo")
        assert any(trace["review_state"] == "pending_human_review" for trace in traces)
    finally:
        _restore_env(original)


def test_reasoning_trace_records_transport_retries(tmp_path, monkeypatch):
    original = _apply_env({
        "STRATEGYOS_TWINS_DATA_DIR": str(tmp_path / "app-data"),
        "STRATEGYOS_MODEL_PROVIDER_ENABLED": "true",
        "STRATEGYOS_LLM_CHAT_ENABLED": "true",
        "STRATEGYOS_RUN_POLICY": "external-approved",
        "STRATEGYOS_APPROVED_EXTERNAL_MODES": "model_provider_use",
        "STRATEGYOS_LLM_API_KEY": "test-key",
        "STRATEGYOS_LLM_BASE_URL": "https://litellm.local",
        "STRATEGYOS_LLM_MODEL": "gpt-4o-mini",
    })
    try:
        import strategyos_mvp.twins.reasoning as reasoning_module

        monkeypatch.setattr(reasoning_module.llm_qa, "chat_status", lambda config: {
            "enabled": True,
            "provider": "litellm",
            "model": "gpt-4o-mini",
        })

        attempts = {"count": 0}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "issues": [
                                                {
                                                    "investigation_id": "ceo_issue_1",
                                                    "type": "kpi_gap",
                                                    "priority": "high",
                                                    "kpi_node_id": "margin_q2",
                                                    "detail": "Margin evidence is stale and needs finance refresh.",
                                                    "owner": "cfo",
                                                    "resolution_hint": "request_data",
                                                    "evidence_refs": [{"finding_id": "F-001"}],
                                                }
                                            ],
                                            "summary": "Recovered after retry.",
                                            "confidence": 0.82,
                                            "review_state": "needs_review",
                                            "citations": [{"finding_id": "F-001"}],
                                        }
                                    )
                                }
                            }
                        ]
                    }
                ).encode("utf-8")

        def fake_urlopen(request, timeout):
            del timeout
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise HTTPError(request.full_url, 503, "Service Unavailable", hdrs=None, fp=BytesIO(b'{"error":"retry"}'))
            return FakeResponse()

        monkeypatch.setattr(reasoning_module.llm_qa, "urlopen", fake_urlopen)
        monkeypatch.setattr(reasoning_module.llm_qa.time, "sleep", lambda *_args, **_kwargs: None)

        repositories = build_repositories(tmp_path / "twins")
        runtime = TwinRuntime(CEO_TWIN, create_twin_state("ceo"), repositories=repositories)
        runtime.run_once()

        traces = repositories.reasoning.list("ceo")
        retry_trace = next(
            trace
            for trace in traces
            if trace.get("transport") and trace["transport"][0].get("retry_reasons") == ["http_503"]
        )
        assert retry_trace["source"] == "litellm"
        assert retry_trace["transport"][0]["outcome"] == "success"
    finally:
        _restore_env(original)


def test_reasoning_trace_preserves_transport_payload_alias(tmp_path, monkeypatch):
    original = _apply_env({
        "STRATEGYOS_TWINS_DATA_DIR": str(tmp_path / "app-data"),
        "STRATEGYOS_MODEL_PROVIDER_ENABLED": "true",
        "STRATEGYOS_LLM_CHAT_ENABLED": "true",
        "STRATEGYOS_RUN_POLICY": "external-approved",
        "STRATEGYOS_APPROVED_EXTERNAL_MODES": "model_provider_use",
        "STRATEGYOS_LLM_API_KEY": "test-key",
        "STRATEGYOS_LLM_BASE_URL": "https://litellm.local",
        "STRATEGYOS_LLM_MODEL": "gpt-4o-mini",
    })
    try:
        import strategyos_mvp.twins.reasoning as reasoning_module

        monkeypatch.setattr(reasoning_module.llm_qa, "chat_status", lambda config: {
            "enabled": True,
            "provider": "litellm",
            "model": "gpt-4o-mini",
        })

        def _fake_call(**_kwargs):
            exc = RuntimeError("LiteLLM provider transient failure after 2 attempts: timeout")
            exc.transport = {
                "attempts": 2,
                "retries": 1,
                "calls": [{"outcome": "failed", "retry_reasons": ["TimeoutError"]}],
            }
            raise exc

        monkeypatch.setattr(reasoning_module, "_call_litellm_reasoning", _fake_call)

        repositories = build_repositories(tmp_path / "twins")
        runtime = TwinRuntime(CEO_TWIN, create_twin_state("ceo"), repositories=repositories)
        runtime.run_once()

        traces = repositories.reasoning.list("ceo")
        retry_trace = next(
            trace
            for trace in traces
            if trace.get("fallback_reason") == "LiteLLM provider transient failure after 2 attempts: timeout"
        )
        assert retry_trace["source"] == "deterministic_fallback"
        assert retry_trace["transport"]["attempts"] == 2
        assert retry_trace["transport"]["retries"] == 1
    finally:
        _restore_env(original)


def test_phase0_to_phase8_surfaces_still_hold(tmp_path):
    original = _apply_env({
        "STRATEGYOS_API_AUTH_ENABLED": "false",
        "STRATEGYOS_TWINS_DATA_DIR": str(tmp_path / "app-data"),
    })
    try:
        status = client.get("/twin/api/status/ceo")
        inbox = client.get("/twin/api/inbox/ceo")
        investigate = client.post("/twin/api/investigate/ceo?query=Why+is+margin+down%3F")
        dashboard = client.get("/twin/ceo")

        assert status.status_code == 200
        assert inbox.status_code == 200
        assert investigate.status_code == 200
        assert dashboard.status_code == 200
        payload = investigate.json()
        assert set(["role", "display_name", "cycle_count", "summary", "governance"]).issubset(payload)
        assert "reasoning_trace_ids" in payload["summary"]
    finally:
        _restore_env(original)
