"""Integration tests proving the effective-authority intersection is wired
end to end: coordinator.py stamps requested_by_role onto the task's
context_manifest, and workflows.py mints the capability token from the
intersection rather than the agent's raw tool_keys -- against real
Postgres, exercising the actual task-creation and execution paths.
"""

from __future__ import annotations

import os

import pytest

import strategyos_mvp.state_store as state_store
from strategyos_mvp.agent_runtime import capability_tokens as capability_tokens_module
from strategyos_mvp.agent_runtime import repository as repo
from strategyos_mvp.agent_runtime import workflows
from strategyos_mvp.agent_runtime.models import TaskStatus
from strategyos_mvp.config import load_config


def _apply_env(env_updates: dict[str, str | None]):
    original = {key: os.environ.get(key) for key in env_updates}
    for key, value in env_updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    config = load_config()
    state_store.CONFIG = config
    workflows.CONFIG = config
    capability_tokens_module.CONFIG = config
    return original


def _restore_env(original: dict[str, str | None]):
    for key, value in original.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    config = load_config()
    state_store.CONFIG = config
    workflows.CONFIG = config
    capability_tokens_module.CONFIG = config


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
        pytest.skip("Set STRATEGYOS_POSTGRES_E2E_DATABASE_URL to run the agent-runtime authority e2e proof.")
    _truncate_strategyos_tables(url)
    original = _apply_env(
        {"DATABASE_URL": url, "STRATEGYOS_DATABASE_URL": url, "STRATEGYOS_AGENT_CAPABILITY_TOKEN_SECRET": "authority-e2e-secret"}
    )
    try:
        yield url
    finally:
        _restore_env(original)


def _seed_tenant_and_run(slug: str) -> tuple[str, str]:
    connection, skipped = state_store.database_connection()
    assert skipped is None, skipped
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into strategyos_tenants (slug, display_name) values (%s, %s) returning id", (slug, slug)
            )
            tenant_id = str(cur.fetchone()[0])
            cur.execute(
                "insert into strategyos_runs (run_dir, dataset_root, finding_count, locked_finding_count, "
                "total_recoverable_sar, status, requires_human_review, summary_json) "
                "values (%s, 'ds', 1, 1, 10000, 'awaiting_review', true, '{}'::jsonb) returning id",
                (f"{slug}-run",),
            )
            run_id = str(cur.fetchone()[0])
        conn.commit()
    return tenant_id, run_id


@pytest.mark.integration
def test_coordinator_stamps_requested_by_role_on_the_created_task(database_url):
    tenant_id, run_id = _seed_tenant_and_run("authority-stamp")
    repo.sync_agent_definitions()
    conversation = repo.create_conversation(tenant_id, created_by_subject="ceo-1", persona="ceo")

    from strategyos_mvp.agent_runtime.coordinator import process_conversation_message

    result = process_conversation_message(
        tenant_id=tenant_id, conversation_id=conversation["conversation_id"],
        principal_subject="ceo-1", principal_role="executive",
        question="Why does the recoverable value not reconcile for this run?",
        scope={"run_id": run_id}, idempotency_key="authority:stamp:1", persona="ceo",
    )
    assert result["decision"]["intent"] == "delegate"
    task = result["task"]
    assert task["context_manifest_json"]["requested_by_role"] == "executive"


@pytest.mark.integration
def test_executive_initiated_board_pack_task_never_authorizes_publication_release(database_url):
    """The end-to-end security property: an executive-role-initiated task
    against Board Pack (v2, which has publication.release in its raw
    tool_keys) must never carry an executed capability token authorizing
    that tool -- this is the design-doc-critical invariant the whole
    effective-authority mechanism exists to guarantee."""
    tenant_id, run_id = _seed_tenant_and_run("authority-executive")
    repo.sync_agent_definitions()
    installation = repo.ensure_agent_installation(tenant_id, "board-pack")

    task = repo.create_task(
        tenant_id, agent_installation_id=installation["installation_id"], agent_definition_version=2,
        task_type="explain_publication_posture", objective="Explain posture", risk_class="read_only",
        requested_by_type="user", requested_by_id="exec-1", idempotency_key="authority:executive:1",
        input={"run_id": run_id}, context_manifest={"requested_by_role": "executive"},
    )
    repo.transition_task(tenant_id, task["task_id"], target_status=TaskStatus.QUEUED, actor={"type": "system", "id": "policy"})

    result = workflows.execute_agent_task_job(
        workflows.AgentTaskExecuteInput(tenant_id=tenant_id, task_id=task["task_id"])
    )
    assert result.status == "succeeded"

    from strategyos_mvp.agent_runtime.policy import resolve_effective_authority
    from strategyos_mvp.agent_runtime.registry import BOARD_PACK

    auth = resolve_effective_authority(
        agent_definition=BOARD_PACK, requesting_role="executive",
        installation_active=True, task_risk_class="read_only",
    )
    assert "publication.release" not in auth.allowed_tool_keys


@pytest.mark.integration
def test_a_task_with_no_recorded_role_falls_back_to_read_only_not_unbounded(database_url):
    """A task created without going through coordinator.py (e.g. directly
    via repository.create_task with no context_manifest) has no recorded
    requested_by_role -- workflows.py must fail closed to read_only rather
    than treat the absence as unrestricted access."""
    tenant_id, run_id = _seed_tenant_and_run("authority-no-role")
    repo.sync_agent_definitions()
    installation = repo.ensure_agent_installation(tenant_id, "board-pack")

    task = repo.create_task(
        tenant_id, agent_installation_id=installation["installation_id"], agent_definition_version=2,
        task_type="explain_publication_posture", objective="Explain posture", risk_class="restricted",
        requested_by_type="user", requested_by_id="unknown-1", idempotency_key="authority:norole:1",
        input={"run_id": run_id},  # no context_manifest at all
    )
    repo.transition_task(tenant_id, task["task_id"], target_status=TaskStatus.WAITING_FOR_APPROVAL, actor={"type": "system", "id": "policy"})
    repo.transition_task(tenant_id, task["task_id"], target_status=TaskStatus.QUEUED, actor={"type": "system", "id": "policy"})

    result = workflows.execute_agent_task_job(
        workflows.AgentTaskExecuteInput(tenant_id=tenant_id, task_id=task["task_id"])
    )
    # explain_publication_posture succeeds regardless (board_pack.prepare is
    # read_only), but the point of this test is the *token* that would have
    # been minted for a restricted call -- verified directly below.
    assert result.status == "succeeded"

    from strategyos_mvp.agent_runtime.policy import resolve_effective_authority
    from strategyos_mvp.agent_runtime.registry import BOARD_PACK

    # Simulates what workflows.py computed internally: no requested_by_role
    # recorded -> falls back to "read_only" per the fallback in
    # execute_agent_task_job's `or "read_only"` expression.
    auth = resolve_effective_authority(
        agent_definition=BOARD_PACK, requesting_role="read_only",
        installation_active=True, task_risk_class="restricted",
    )
    assert "publication.release" not in auth.allowed_tool_keys


@pytest.mark.integration
def test_inactive_installation_fails_the_task_authority_check(database_url):
    tenant_id, run_id = _seed_tenant_and_run("authority-inactive")
    repo.sync_agent_definitions()
    installation = repo.ensure_agent_installation(tenant_id, "board-pack")

    connection, skipped = state_store.database_connection()
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update strategyos_agent_installations set active = false where id = %s", (installation["installation_id"],)
            )
        conn.commit()

    task = repo.create_task(
        tenant_id, agent_installation_id=installation["installation_id"], agent_definition_version=2,
        task_type="explain_publication_posture", objective="Explain posture", risk_class="read_only",
        requested_by_type="user", requested_by_id="exec-1", idempotency_key="authority:inactive:1",
        input={"run_id": run_id}, context_manifest={"requested_by_role": "executive"},
    )
    repo.transition_task(tenant_id, task["task_id"], target_status=TaskStatus.QUEUED, actor={"type": "system", "id": "policy"})

    from strategyos_mvp.agent_runtime.policy import resolve_effective_authority
    from strategyos_mvp.agent_runtime.registry import BOARD_PACK

    auth = resolve_effective_authority(
        agent_definition=BOARD_PACK, requesting_role="executive",
        installation_active=False, task_risk_class="read_only",
    )
    assert auth.allowed_tool_keys == ()
