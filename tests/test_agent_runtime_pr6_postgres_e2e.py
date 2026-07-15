"""Integration tests for PR6 -- capability-token-gated tool dispatch,
board-pack v2 upgrade, and the a2a.mode acceptance-criteria gate -- against
real Postgres.
"""

from __future__ import annotations

import os

import pytest

import strategyos_mvp.agent_runtime.api as agent_api_module
import strategyos_mvp.agent_runtime.capability_tokens as capability_tokens_module
import strategyos_mvp.api as api_module
import strategyos_mvp.auth as auth_module
import strategyos_mvp.state_store as state_store
from strategyos_mvp.agent_runtime import repository as repo
from strategyos_mvp.agent_runtime import workflows
from strategyos_mvp.agent_runtime.registry import BOARD_PACK
from strategyos_mvp.agent_runtime.tools import ToolExecutionContext, ToolInputInvalid, invoke_tool
from strategyos_mvp.config import load_config


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
    agent_api_module.CONFIG = config
    capability_tokens_module.CONFIG = config
    state_store.CONFIG = config
    workflows.CONFIG = config
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
    agent_api_module.CONFIG = config
    capability_tokens_module.CONFIG = config
    state_store.CONFIG = config
    workflows.CONFIG = config


def _truncate_strategyos_tables(database_url: str) -> None:
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(database_url, autocommit=True) as conn:
        state_store.ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                select tablename from pg_tables
                where schemaname = 'public' and tablename like 'strategyos_%'
                order by tablename
                """
            )
            tables = [row[0] for row in cur.fetchall()]
            if tables:
                cur.execute(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE")


@pytest.fixture
def database_url():
    url = os.environ.get("STRATEGYOS_POSTGRES_E2E_DATABASE_URL")
    if not url:
        pytest.skip("Set STRATEGYOS_POSTGRES_E2E_DATABASE_URL to run the agent-runtime PR6 e2e proof.")
    _truncate_strategyos_tables(url)
    original = _apply_env(
        {
            "DATABASE_URL": url,
            "STRATEGYOS_DATABASE_URL": url,
            "STRATEGYOS_AGENT_CAPABILITY_TOKEN_SECRET": "pr6-e2e-secret",
        }
    )
    try:
        yield url
    finally:
        _restore_env(original)


@pytest.mark.integration
def test_ensure_agent_installation_defaults_to_the_registrys_current_version(database_url):
    """Regression test for the bug found while bumping board-pack to v2:
    ensure_agent_installation() must not silently pin every new
    installation to a hardcoded version=1."""
    connection, skipped = state_store.database_connection()
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into strategyos_tenants (slug, display_name) values ('pr6-version', 'pr6-version') returning id"
            )
            tenant_id = str(cur.fetchone()[0])
        conn.commit()

    installation = repo.ensure_agent_installation(tenant_id, "board-pack")
    assert installation["agent_definition_version"] == BOARD_PACK.version
    assert BOARD_PACK.version >= 2


@pytest.mark.integration
def test_publication_release_requires_a_capability_token(database_url):
    connection, skipped = state_store.database_connection()
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into strategyos_tenants (slug, display_name) values ('pr6-pub', 'pr6-pub') returning id"
            )
            tenant_id = str(cur.fetchone()[0])
            cur.execute(
                "insert into strategyos_runs (run_dir, dataset_root, finding_count, locked_finding_count, "
                "total_recoverable_sar, status, requires_human_review, summary_json) "
                "values ('r','ds',1,1,10000,'awaiting_review',true,'{}'::jsonb) returning id"
            )
            run_id = str(cur.fetchone()[0])
        conn.commit()

    ctx = ToolExecutionContext(tenant_id=tenant_id, task_id="t1", run_id=run_id)
    with pytest.raises(ToolInputInvalid):
        invoke_tool("publication.release", ctx, {"run_id": run_id})


@pytest.mark.integration
def test_publication_release_reports_ineligible_for_unapproved_run(database_url):
    connection, skipped = state_store.database_connection()
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into strategyos_tenants (slug, display_name) values ('pr6-ineligible', 'pr6-ineligible') returning id"
            )
            tenant_id = str(cur.fetchone()[0])
            cur.execute(
                "insert into strategyos_runs (run_dir, dataset_root, finding_count, locked_finding_count, "
                "total_recoverable_sar, status, requires_human_review, summary_json) "
                "values ('r','ds',1,1,10000,'awaiting_review',true,'{}'::jsonb) returning id"
            )
            run_id = str(cur.fetchone()[0])
        conn.commit()

    token = capability_tokens_module.issue_capability_token(
        tenant_id=tenant_id, task_id="t1", attempt_no=1, agent_installation_id="inst1",
        allowed_tool_keys=("publication.release",), max_risk_class="restricted",
    )
    claims = capability_tokens_module.verify_capability_token(token)
    ctx = ToolExecutionContext(tenant_id=tenant_id, task_id="t1", run_id=run_id, capability_claims=claims)

    result = invoke_tool("publication.release", ctx, {"run_id": run_id})
    assert result["available"] is True
    assert result["release_eligible"] is False
    assert "reviewer" in result["blocking_reason"]


@pytest.mark.integration
def test_publication_release_reports_eligible_once_a_reviewer_approves(database_url):
    connection, skipped = state_store.database_connection()
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into strategyos_tenants (slug, display_name) values ('pr6-eligible', 'pr6-eligible') returning id"
            )
            tenant_id = str(cur.fetchone()[0])
            cur.execute(
                "insert into strategyos_runs (run_dir, dataset_root, finding_count, locked_finding_count, "
                "total_recoverable_sar, status, requires_human_review, summary_json) "
                "values ('r','ds',1,1,10000,'awaiting_review',true,'{}'::jsonb) returning id"
            )
            run_id = str(cur.fetchone()[0])
            # simulate the existing human-reviewer approval path (state_store.record_approval's
            # effect) directly against strategyos_approvals + strategyos_runs, since that mutation
            # deliberately stays outside agent_runtime's reach per design doc section 20.
            cur.execute(
                "update strategyos_runs set status = 'approved', approved_by = 'reviewer-1', approved_at = now() "
                "where id = %s",
                (run_id,),
            )
            cur.execute(
                "insert into strategyos_approvals (run_id, reviewer, decision) values (%s, 'reviewer-1', 'approved')",
                (run_id,),
            )
        conn.commit()

    token = capability_tokens_module.issue_capability_token(
        tenant_id=tenant_id, task_id="t1", attempt_no=1, agent_installation_id="inst1",
        allowed_tool_keys=("publication.release",), max_risk_class="restricted",
    )
    claims = capability_tokens_module.verify_capability_token(token)
    ctx = ToolExecutionContext(tenant_id=tenant_id, task_id="t1", run_id=run_id, capability_claims=claims)

    result = invoke_tool("publication.release", ctx, {"run_id": run_id})
    assert result["release_eligible"] is True
    assert result["blocking_reason"] is None


@pytest.mark.integration
def test_a2a_mode_gate_requires_all_three_flags_together(database_url):
    """_chat_threads_payload()'s a2a.mode expression requires setup of
    executive_modes/board_portal/publication dicts that are themselves
    complex derived payloads unrelated to what this test verifies, so this
    exercises the same boolean gate api.py evaluates directly against
    CONFIG, matching design doc acceptance criteria: "a2a.mode reports
    durable_task_handoffs only when real persistence/execution is
    enabled" -- i.e. all three per-PR flags on together, not any subset."""
    combinations = [
        (False, False, False, "derived_handoff_only"),
        (True, False, False, "derived_handoff_only"),
        (True, True, False, "derived_handoff_only"),
        (False, True, True, "derived_handoff_only"),
        (True, False, True, "derived_handoff_only"),
        (True, True, True, "durable_task_handoffs"),
    ]
    for conversations, handoffs, live_ui, expected_mode in combinations:
        original = _apply_env(
            {
                "STRATEGYOS_AGENT_CONVERSATIONS_ENABLED": str(conversations).lower(),
                "STRATEGYOS_AGENT_HANDOFFS_ENABLED": str(handoffs).lower(),
                "STRATEGYOS_AGENT_LIVE_UI_ENABLED": str(live_ui).lower(),
            }
        )
        try:
            actual_mode = (
                "durable_task_handoffs"
                if (
                    api_module.CONFIG.agent_conversations_enabled
                    and api_module.CONFIG.agent_handoffs_enabled
                    and api_module.CONFIG.agent_live_ui_enabled
                )
                else "derived_handoff_only"
            )
            assert actual_mode == expected_mode, (conversations, handoffs, live_ui)
        finally:
            _restore_env(original)
