from __future__ import annotations

import atexit
import hashlib
import json
import math
import re
import threading
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from .citation_resolver import resolve_citation
from .config import CONFIG
from .evidence import row_locator, sha256_file
from .ingestion import DataBundle
from .models import AuditEvent, Finding
from .oracle_finance import OracleCanonicalSnapshot
from .source_claims import (
    ClaimDraft,
    ClaimKind,
    ProductionMethod,
    SourceAccessPolicy,
    SourceRegistration,
    stable_key,
)


_SCHEMA_READY_DATABASES: set[tuple[str, str, str, str]] = set()
_SCHEMA_READY_LOCK = threading.RLock()


def create_run(
    summary_seed: dict[str, Any], *, requires_human_review: bool
) -> dict[str, Any]:
    summary_seed = {**summary_seed, "tenant_context": {
        **dict(summary_seed.get("tenant_context") or {}), "tenant_id": CONFIG.tenant_slug}}
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into strategyos_runs
                    (run_dir, dataset_root, finding_count, locked_finding_count, total_recoverable_sar,
                     status, current_stage, requires_human_review, summary_json, tenant_key, business_unit_scope)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb)
                returning id, created_at, status, current_stage, requires_human_review, approved_at, approved_by, summary_json
                """,
                (
                    text_value(summary_seed.get("run_dir")) or "pending",
                    text_value(
                        summary_seed.get("dataset_root") or summary_seed.get("dataset")
                    )
                    or "pending",
                    int(
                        summary_seed.get(
                            "finding_count", summary_seed.get("findings", 0)
                        )
                        or 0
                    ),
                    int(
                        summary_seed.get(
                            "locked_finding_count",
                            summary_seed.get("locked_findings", 0),
                        )
                        or 0
                    ),
                    money_value(summary_seed.get("total_recoverable_sar")) or 0.0,
                    text_value(summary_seed.get("status")) or "running",
                    text_value(summary_seed.get("current_stage")),
                    requires_human_review,
                    json_blob(summary_seed),
                    CONFIG.tenant_slug,
                    json_blob(summary_seed.get("business_units") or []),
                ),
            )
            record = fetchone_dict(cur)
        conn.commit()
    assert record is not None
    normalized = normalize_record(record)
    normalized["run_id"] = normalized.pop("id")
    normalized["approval_status"] = (
        "pending" if requires_human_review else "not_required"
    )
    return normalized


def run_job_request_hash(request_payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"tenant_id": CONFIG.tenant_slug, "request": request_payload},
        default=json_value,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_run_job(
    request_payload: dict[str, Any],
    *,
    submitted_by: str | None = None,
    execution_mode: str = "hatchet",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {**dict(metadata or {}), "tenant_context": {"tenant_id": CONFIG.tenant_slug}}
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    request_hash = run_job_request_hash(request_payload)
    assert connection is not None
    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            # Serialize submissions for the exact same governed input contract.
            # The request hash is derived from dataset/source-pack + run options,
            # so this prevents duplicate reprocessing without blocking unrelated
            # tenants or datasets.
            cur.execute("select pg_advisory_xact_lock(hashtext(%s))", (request_hash,))
            cur.execute(
                """
                select id, status
                from strategyos_run_jobs
                where request_hash = %s and status in ('queued', 'running')
                order by created_at desc
                limit 1
                """,
                (request_hash,),
            )
            active = fetchone_dict(cur)
            if active is not None:
                raise ValueError(
                    f"Analysis is already {active.get('status') or 'running'} for this dataset."
                )
            cur.execute(
                """
                insert into strategyos_run_jobs
                    (execution_mode, status, request_hash, request_json, submitted_by, metadata_json)
                values (%s, 'queued', %s, %s::jsonb, %s, %s::jsonb)
                returning id, created_at, updated_at, execution_mode, status, request_hash, request_json,
                          submitted_by, hatchet_run_id, strategyos_run_id, retry_count, failure_reason,
                          metadata_json, started_at, finished_at
                """,
                (
                    execution_mode,
                    request_hash,
                    json_blob(request_payload),
                    submitted_by,
                    json_blob(metadata or {}),
                ),
            )
            record = fetchone_dict(cur)
        conn.commit()
    assert record is not None
    return normalize_run_job_record(record)


def update_run_job(
    job_id: str,
    *,
    status: str | None = None,
    hatchet_run_id: str | None = None,
    strategyos_run_id: str | None = None,
    failure_reason: str | None = None,
    metadata: dict[str, Any] | None = None,
    increment_retry: bool = False,
) -> dict[str, Any]:
    from .access_scope import guard_reference
    guard_reference("job", job_id)
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    normalized_run_id = uuid_value(strategyos_run_id)
    terminal_status = status in {"succeeded", "failed", "cancelled"}
    assert connection is not None
    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                update strategyos_run_jobs
                set status = coalesce(%s::text, status),
                    hatchet_run_id = coalesce(%s::text, hatchet_run_id),
                    strategyos_run_id = coalesce(%s::uuid, strategyos_run_id),
                    failure_reason = case when %s::text is null then failure_reason else %s::text end,
                    metadata_json = metadata_json || %s::jsonb,
                    retry_count = retry_count + %s::integer,
                    started_at = case
                        when %s::text = 'running' then coalesce(started_at, now())
                        else started_at
                    end,
                    finished_at = case
                        when %s::boolean then coalesce(finished_at, now())
                        else finished_at
                    end,
                    updated_at = now()
                where id = %s
                returning id, created_at, updated_at, execution_mode, status, request_hash, request_json,
                          submitted_by, hatchet_run_id, strategyos_run_id, retry_count, failure_reason,
                          metadata_json, started_at, finished_at
                """,
                (
                    status,
                    hatchet_run_id,
                    normalized_run_id,
                    failure_reason,
                    failure_reason,
                    json_blob(metadata or {}),
                    1 if increment_retry else 0,
                    status,
                    terminal_status,
                    job_id,
                ),
            )
            record = fetchone_dict(cur)
        conn.commit()
    if record is None:
        return {"status": "missing", "job_id": job_id}
    return normalize_run_job_record(record)


def get_run_job(job_id: str) -> dict[str, Any]:
    from .access_scope import guard_reference
    guard_reference("job", job_id)
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, created_at, updated_at, execution_mode, status, request_hash, request_json,
                       submitted_by, hatchet_run_id, strategyos_run_id, retry_count, failure_reason,
                       metadata_json, started_at, finished_at
                from strategyos_run_jobs
                where id = %s
                """,
                (job_id,),
            )
            record = fetchone_dict(cur)
    if record is None:
        return {"status": "missing", "job_id": job_id}
    return normalize_run_job_record(record)


def update_run_status(
    run_id: str,
    *,
    status: str,
    current_stage: str | None = None,
    approved_by: str | None = None,
) -> dict[str, Any]:
    from .access_scope import guard_run
    guard_run(run_id)
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                update strategyos_runs
                set status = %s,
                    current_stage = %s,
                    approved_by = coalesce(%s, approved_by),
                    approved_at = case
                        when %s = 'approved' then coalesce(approved_at, now())
                        else approved_at
                    end
                where id = %s
                returning id, created_at, status, current_stage, requires_human_review, approved_at, approved_by, summary_json
                """,
                (status, current_stage, approved_by, status, run_id),
            )
            record = fetchone_dict(cur)
        conn.commit()
    if record is None:
        return {"status": "missing", "run_id": run_id}
    normalized = normalize_record(record)
    normalized["run_id"] = normalized.pop("id")
    return normalized


def persist_checkpoint(
    run_id: str,
    stage: str,
    status: str,
    state: dict[str, Any],
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .access_scope import guard_run
    guard_run(run_id)
    connection, skipped = database_connection()
    if skipped is not None:
        return {
            **skipped,
            "checkpoint_id": None,
            "run_id": run_id,
            "stage": stage,
            "state_json": state,
            "summary_json": summary or {},
        }

    assert connection is not None
    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into strategyos_run_checkpoints (run_id, stage, status, state_json, summary_json)
                values (%s, %s, %s, %s::jsonb, %s::jsonb)
                returning id, run_id, stage, status, state_json, summary_json, created_at
                """,
                (run_id, stage, status, json_blob(state), json_blob(summary or {})),
            )
            checkpoint = fetchone_dict(cur)
            cur.execute(
                """
                update strategyos_runs
                set status = %s,
                    current_stage = %s
                where id = %s
                """,
                (status, stage, run_id),
            )
        conn.commit()
    assert checkpoint is not None
    normalized = normalize_record(checkpoint)
    normalized["checkpoint_id"] = normalized.pop("id")
    return normalized


def latest_checkpoint(run_id: str) -> dict[str, Any] | None:
    from .access_scope import guard_run
    guard_run(run_id)
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, run_id, stage, status, state_json, summary_json, created_at
                from strategyos_run_checkpoints
                where run_id = %s
                order by created_at desc
                limit 1
                """,
                (run_id,),
            )
            checkpoint = fetchone_dict(cur)
    if checkpoint is None:
        return None
    normalized = normalize_record(checkpoint)
    normalized["checkpoint_id"] = normalized.pop("id")
    return normalized


def get_checkpoint_detail(checkpoint_id: str) -> dict[str, Any]:
    from .access_scope import guard_reference
    guard_reference("checkpoint", checkpoint_id)
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, run_id, stage, status, state_json, summary_json, created_at
                from strategyos_run_checkpoints
                where id = %s
                """,
                (checkpoint_id,),
            )
            checkpoint = fetchone_dict(cur)
    if checkpoint is None:
        return {"status": "missing", "checkpoint_id": checkpoint_id}
    normalized = normalize_record(checkpoint)
    normalized["checkpoint_id"] = normalized.pop("id")
    return normalized


def get_run_detail(run_id: str) -> dict[str, Any]:
    from .access_scope import guard_run
    guard_run(run_id)
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, created_at, run_dir, dataset_root, finding_count, locked_finding_count,
                       total_recoverable_sar, status, current_stage, requires_human_review,
                       review_claimed_by, review_claimed_at,
                       approved_at, approved_by, summary_json
                from strategyos_runs
                where id = %s
                """,
                (run_id,),
            )
            run_record = fetchone_dict(cur)
    if run_record is None:
        return {"status": "missing", "run_id": run_id}

    run_data = normalize_record(run_record)
    checkpoint = latest_checkpoint(run_id)
    approval = approval_status_for_run(run_id)
    return {
        "run_id": str(run_data.pop("id")),
        **run_data,
        "review_assignment": review_assignment_payload(run_data),
        "latest_checkpoint": checkpoint,
        "approval": approval,
    }


def executive_snapshot_for_run(run_id: str) -> dict[str, Any]:
    from .access_scope import guard_run
    guard_run(run_id)
    """Load the executive truth surface from persisted relational records.

    This deliberately does not fall back to run artifacts. Callers can choose an
    explicitly labelled artifact fallback, but a payload returned as ``ok`` here
    is backed by the StrategyOS Postgres tables named in its provenance.
    """
    normalized_run_id = uuid_value(run_id)
    if normalized_run_id is None:
        return {
            "status": "missing",
            "reason": "The current run does not have a database identity.",
        }

    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    try:
        with connection as conn:
            ensure_data_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select
                        r.id,
                        r.created_at,
                        r.run_dir,
                        r.dataset_root,
                        r.finding_count,
                        r.locked_finding_count,
                        r.total_recoverable_sar,
                        r.status,
                        r.current_stage,
                        r.requires_human_review,
                        r.approved_at,
                        r.approved_by,
                        r.summary_json,
                        a.decision as latest_approval_decision
                    from strategyos_runs r
                    left join lateral (
                        select decision
                        from strategyos_approvals
                        where run_id = r.id
                        order by created_at desc
                        limit 1
                    ) a on true
                    where r.id = %s
                    """,
                    (normalized_run_id,),
                )
                run_record = fetchone_dict(cur)
                if run_record is None:
                    return {
                        "status": "missing",
                        "reason": "The current run is not present in the database.",
                    }

                cur.execute(
                    """
                    select
                        f.finding_id,
                        f.pattern_type,
                        f.vendor_id,
                        f.vendor_name,
                        f.status,
                        f.confidence,
                        f.leakage_sar,
                        f.recoverable_sar,
                        f.finding_json,
                        count(c.id) as citation_count,
                        count(c.id) filter (where c.resolved) as resolved_citation_count,
                        lower(f.status) = 'challenged' as challenged
                    from strategyos_findings f
                    left join strategyos_finding_citations c
                      on c.run_id = f.run_id and c.finding_id = f.finding_id
                    where f.run_id = %s
                    group by f.id
                    order by f.recoverable_sar desc, f.finding_id
                    """,
                    (normalized_run_id,),
                )
                finding_records = fetchall_dicts(cur)

                cur.execute(
                    """
                    select artifact_name, local_path, object_uri
                    from strategyos_artifacts
                    where run_id = %s
                    order by created_at, artifact_name
                    """,
                    (normalized_run_id,),
                )
                artifact_records = fetchall_dicts(cur)

                cur.execute(
                    """
                    select round_no, actor, finding_id, action, detail, event_json, created_at
                    from strategyos_agent_events
                    where run_id = %s
                    order by created_at desc
                    limit 50
                    """,
                    (normalized_run_id,),
                )
                event_records = fetchall_dicts(cur)
    except Exception:
        return {
            "status": "failed",
            "reason": "The database executive snapshot is temporarily unavailable.",
        }

    run_data = normalize_record(run_record)
    stored_summary = run_data.get("summary_json")
    summary = dict(stored_summary) if isinstance(stored_summary, dict) else {}
    approval_status = str(run_data.get("latest_approval_decision") or "").lower()
    if not approval_status:
        approval_status = "approved" if run_data.get("approved_at") else (
            "pending" if run_data.get("requires_human_review") else "not_required"
        )
    summary.update(
        {
            "run_id": str(run_data.get("id")),
            "created_at": run_data.get("created_at"),
            "run_dir": run_data.get("run_dir"),
            "dataset": run_data.get("dataset_root"),
            "findings": run_data.get("finding_count"),
            "locked_findings": run_data.get("locked_finding_count"),
            "total_recoverable_sar": run_data.get("total_recoverable_sar"),
            "status": run_data.get("status"),
            "current_stage": run_data.get("current_stage"),
            "requires_human_review": bool(run_data.get("requires_human_review")),
            "approved_at": run_data.get("approved_at"),
            "approved_by": run_data.get("approved_by"),
            "approval_status": approval_status,
        }
    )

    findings: list[dict[str, Any]] = []
    for record in finding_records:
        row = normalize_record(record)
        finding_json = row.get("finding_json")
        finding_payload = finding_json if isinstance(finding_json, dict) else {}
        pattern_type = str(row.get("pattern_type") or finding_payload.get("pattern_type") or "")
        findings.append(
            {
                "finding_id": str(row.get("finding_id") or ""),
                "title": str(finding_payload.get("title") or row.get("finding_id") or "Finding"),
                "pattern_type": pattern_type,
                "classification": str(finding_payload.get("classification") or ""),
                "confidence": str(row.get("confidence") or ""),
                "status": str(row.get("status") or ""),
                "recoverable_sar": row.get("recoverable_sar"),
                "leakage_sar": row.get("leakage_sar"),
                "owner": str(row.get("vendor_name") or row.get("vendor_id") or ""),
                # The recommended action and who owns it are written into
                # finding_json by persist_findings (asdict of the whole Finding),
                # but were never read back, so the card could only show a value
                # with no next step. Both are real generated text -- e.g. "AP
                # should immediately recover the duplicate payment..." -- not
                # inferred here.
                "remediation": str(finding_payload.get("remediation") or ""),
                "rationale": str(finding_payload.get("rationale") or ""),
                "citation_count": int(row.get("citation_count") or 0),
                "resolved_citation_count": int(row.get("resolved_citation_count") or 0),
                "challenged": bool(row.get("challenged")),
            }
        )

    artifacts = {
        str(record.get("artifact_name")): str(record.get("object_uri") or record.get("local_path"))
        for record in (normalize_record(item) for item in artifact_records)
        if record.get("artifact_name") and (record.get("object_uri") or record.get("local_path"))
    }
    citation_count = sum(int(row.get("citation_count") or 0) for row in findings)
    resolved_count = sum(int(row.get("resolved_citation_count") or 0) for row in findings)
    return {
        "status": "ok",
        "source": "database",
        "summary": summary,
        "findings": findings,
        "audit_summary": {
            "status": "ok",
            "run_id": normalized_run_id,
            "citation_count": citation_count,
            "resolved_count": resolved_count,
            "challenged_finding_ids": [
                row["finding_id"] for row in findings if row.get("challenged")
            ],
        },
        "artifacts": artifacts,
        "agent_events": [normalize_record(record) for record in event_records],
    }


def list_pending_reviews() -> list[dict[str, Any]] | dict[str, Any]:
    from .access_scope import run_predicate, source_read_allowed
    scope_where, scope_params = run_predicate()
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select
                    r.id,
                    r.created_at,
                    r.run_dir,
                    r.dataset_root,
                    r.status,
                    r.current_stage,
                    r.requires_human_review,
                    rc.id as checkpoint_id,
                    rc.stage as checkpoint_stage,
                    rc.created_at as checkpoint_created_at,
                    rc.summary_json as checkpoint_summary_json,
                    r.review_claimed_by,
                    r.review_claimed_at,
                    a.id as approval_id,
                    a.decision,
                    a.created_at as approval_created_at
                from strategyos_runs r
                left join lateral (
                    select id, stage, created_at, summary_json
                    from strategyos_run_checkpoints
                    where run_id = r.id
                    order by created_at desc
                    limit 1
                ) rc on true
                left join lateral (
                    select id, decision, created_at
                    from strategyos_approvals
                    where run_id = r.id
                    order by created_at desc
                    limit 1
                ) a on true
                where r.requires_human_review = true
                  and r.status = 'awaiting_review'
                  and coalesce(a.decision, 'pending') not in ('approved', 'rejected')
                  and ({scope_where})
                order by coalesce(rc.created_at, r.created_at) desc
                """,
                scope_params,
            )
            items = []
            for normalized in (normalize_record(record) for record in fetchall_dicts(cur)):
                run_id = str(normalized.pop("id"))
                items.append(
                    {
                        "run_id": run_id,
                        **normalized,
                        "review_assignment": review_assignment_payload(normalized),
                    }
                )
    # Source authorization opens its own transaction. Release schema/run locks
    # before checking policies; never nest that connection inside this one.
    return [item for item in items if source_read_allowed(item["run_id"])]


def list_recent_runs(limit: int = 12) -> list[dict[str, Any]] | dict[str, Any]:
    from .access_scope import run_predicate, source_read_allowed
    scope_where, scope_params = run_predicate()
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select
                    r.id,
                    r.created_at,
                    r.run_dir,
                    r.dataset_root,
                    r.finding_count,
                    r.locked_finding_count,
                    r.total_recoverable_sar,
                    r.status,
                    r.current_stage,
                    r.requires_human_review,
                    r.review_claimed_by,
                    r.review_claimed_at,
                    r.approved_at,
                    r.approved_by,
                    r.summary_json,
                    rc.id as checkpoint_id,
                    rc.stage as checkpoint_stage,
                    rc.status as checkpoint_status,
                    rc.created_at as checkpoint_created_at,
                    a.id as approval_id,
                    a.decision as approval_decision,
                    a.reviewer as approval_reviewer,
                    a.reviewer_subject as approval_reviewer_subject,
                    a.reviewer_role as approval_reviewer_role,
                    a.comment as approval_comment,
                    a.created_at as approval_created_at
                from strategyos_runs r
                left join lateral (
                    select id, stage, status, created_at
                    from strategyos_run_checkpoints
                    where run_id = r.id
                    order by created_at desc
                    limit 1
                ) rc on true
                left join lateral (
                    select id, decision, reviewer, reviewer_subject, reviewer_role, comment, created_at
                    from strategyos_approvals
                    where run_id = r.id
                    order by created_at desc
                    limit 1
                ) a on true
                where ({scope_where})
                order by coalesce(rc.created_at, r.created_at) desc
                limit %s
                """,
                (*scope_params, max(1, min(int(limit), 50))),
            )
            items = []
            for normalized in (normalize_record(record) for record in fetchall_dicts(cur)):
                run_id = str(normalized.pop("id"))
                approval_status = "not_required"
                if normalized.get("requires_human_review"):
                    approval_status = "pending"
                if normalized.get("approval_decision"):
                    approval_status = str(normalized.get("approval_decision"))
                items.append(
                    {
                        "run_id": run_id,
                        **normalized,
                        "review_assignment": review_assignment_payload(normalized),
                        "approval_status": approval_status,
                    }
                )
    return [item for item in items if source_read_allowed(item["run_id"])]


def claim_pending_review(
    run_id: str,
    reviewer_subject: str,
) -> dict[str, Any]:
    from .access_scope import guard_run
    guard_run(run_id)
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                update strategyos_runs
                set review_claimed_by = %s,
                    review_claimed_at = case
                        when review_claimed_by = %s then coalesce(review_claimed_at, now())
                        else now()
                    end
                where id = %s
                  and requires_human_review = true
                  and status = 'awaiting_review'
                  and (review_claimed_by is null or review_claimed_by = %s)
                returning id, status, current_stage, requires_human_review, review_claimed_by, review_claimed_at
                """,
                (reviewer_subject, reviewer_subject, run_id, reviewer_subject),
            )
            record = fetchone_dict(cur)
            if record is not None:
                conn.commit()
                normalized = normalize_record(record)
                return {
                    "run_id": str(normalized.pop("id")),
                    **normalized,
                    "review_assignment": review_assignment_payload(normalized),
                }

            cur.execute(
                """
                select id, status, current_stage, requires_human_review, review_claimed_by, review_claimed_at
                from strategyos_runs
                where id = %s
                """,
                (run_id,),
            )
            current = fetchone_dict(cur)

    if current is None:
        return {"status": "missing", "run_id": run_id}

    normalized = normalize_record(current)
    assignment = review_assignment_payload(normalized)
    claimed_by = assignment.get("claimed_by")
    if claimed_by and claimed_by != reviewer_subject:
        return {
            "status": "conflict",
            "run_id": run_id,
            "reason": f"Run '{run_id}' is already claimed by {claimed_by}.",
            "review_assignment": assignment,
        }
    return {
        "status": "conflict",
        "run_id": run_id,
        "reason": f"Run '{run_id}' is not available for claim.",
        "review_assignment": assignment,
    }


def unclaim_pending_review(
    run_id: str,
    reviewer_subject: str,
) -> dict[str, Any]:
    from .access_scope import guard_run
    guard_run(run_id)
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                update strategyos_runs
                set review_claimed_by = null,
                    review_claimed_at = null
                where id = %s
                  and requires_human_review = true
                  and status = 'awaiting_review'
                  and review_claimed_by = %s
                returning id, status, current_stage, requires_human_review, review_claimed_by, review_claimed_at
                """,
                (run_id, reviewer_subject),
            )
            record = fetchone_dict(cur)
            if record is not None:
                conn.commit()
                normalized = normalize_record(record)
                return {
                    "run_id": str(normalized.pop("id")),
                    **normalized,
                    "review_assignment": review_assignment_payload(normalized),
                }

            cur.execute(
                """
                select id, status, current_stage, requires_human_review, review_claimed_by, review_claimed_at
                from strategyos_runs
                where id = %s
                """,
                (run_id,),
            )
            current = fetchone_dict(cur)

    if current is None:
        return {"status": "missing", "run_id": run_id}

    normalized = normalize_record(current)
    assignment = review_assignment_payload(normalized)
    claimed_by = assignment.get("claimed_by")
    if claimed_by and claimed_by != reviewer_subject:
        return {
            "status": "conflict",
            "run_id": run_id,
            "reason": f"Run '{run_id}' is claimed by {claimed_by}; only the current reviewer can unclaim it.",
            "review_assignment": assignment,
        }
    return {
        "status": "conflict",
        "run_id": run_id,
        "reason": f"Run '{run_id}' is not currently claimed.",
        "review_assignment": assignment,
    }


def record_approval(
    run_id: str,
    checkpoint_id: str,
    reviewer: str,
    reviewer_subject: str,
    reviewer_role: str,
    decision: str,
    comment: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    from .access_scope import guard_run
    guard_run(run_id)
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, status, current_stage, requires_human_review, review_claimed_by, review_claimed_at
                from strategyos_runs
                where id = %s
                for update
                """,
                (run_id,),
            )
            run_record = fetchone_dict(cur)
            if run_record is None:
                return {"status": "missing", "run_id": run_id}
            run_data = normalize_record(run_record)
            if str(run_data.get("status") or "") != "awaiting_review":
                return {
                    "status": "conflict",
                    "run_id": run_id,
                    "reason": f"Run '{run_id}' is not awaiting review.",
                    "review_assignment": review_assignment_payload(run_data),
                }
            claimed_by = text_value(run_data.get("review_claimed_by"))
            if reviewer_role == "reviewer" and claimed_by != reviewer_subject:
                reason = (
                    f"Run '{run_id}' must be claimed before a reviewer decision can be recorded."
                    if claimed_by is None
                    else f"Run '{run_id}' is claimed by {claimed_by}."
                )
                return {
                    "status": "conflict",
                    "run_id": run_id,
                    "reason": reason,
                    "review_assignment": review_assignment_payload(run_data),
                }
            cur.execute(
                """
                insert into strategyos_approvals
                    (run_id, checkpoint_id, reviewer, reviewer_subject, reviewer_role, decision, comment, payload)
                values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                returning id, run_id, checkpoint_id, finding_id, reviewer, reviewer_subject, reviewer_role,
                          decision, comment, payload, created_at
                """,
                (
                    run_id,
                    checkpoint_id,
                    reviewer,
                    reviewer_subject,
                    reviewer_role,
                    decision,
                    comment,
                    json_blob(payload),
                ),
            )
            approval = fetchone_dict(cur)
            cur.execute(
                """
                update strategyos_runs
                set status = %s,
                    review_claimed_by = null,
                    review_claimed_at = null,
                    approved_by = case when %s = 'approved' then %s else approved_by end,
                    approved_at = case when %s = 'approved' then coalesce(approved_at, now()) else approved_at end
                where id = %s
                returning current_stage
                """,
                (
                    run_status_for_decision(decision),
                    decision,
                    reviewer,
                    decision,
                    run_id,
                ),
            )
            run_row = cur.fetchone()
        conn.commit()
    assert approval is not None
    normalized = normalize_record(approval)
    normalized["approval_id"] = normalized.pop("id")
    normalized["run_status"] = run_status_for_decision(decision)
    normalized["current_stage"] = (
        str(run_row[0]) if run_row and run_row[0] is not None else None
    )
    return normalized


def approval_status_for_run(run_id: str) -> dict[str, Any]:
    from .access_scope import guard_run
    guard_run(run_id)
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, status, current_stage, requires_human_review, approved_at, approved_by
                       , review_claimed_by, review_claimed_at
                from strategyos_runs
                where id = %s
                """,
                (run_id,),
            )
            run_record = fetchone_dict(cur)
            if run_record is None:
                return {"status": "missing", "run_id": run_id}
            cur.execute(
                """
                select id, run_id, checkpoint_id, reviewer, reviewer_subject, reviewer_role, decision, comment, payload, created_at
                from strategyos_approvals
                where run_id = %s
                order by created_at desc
                limit 1
                """,
                (run_id,),
            )
            approval_record = fetchone_dict(cur)

    run_data = normalize_record(run_record)
    requires_human_review = bool(run_data.get("requires_human_review"))
    approval_status = "not_required"
    if requires_human_review:
        approval_status = "pending"
    if approval_record is not None:
        approval_data = normalize_record(approval_record)
        approval_status = str(approval_data.get("decision"))
    else:
        approval_data = None

    return {
        "run_id": str(run_data.pop("id")),
        "run_status": run_data.get("status"),
        "current_stage": run_data.get("current_stage"),
        "requires_human_review": requires_human_review,
        "approved_at": run_data.get("approved_at"),
        "approved_by": run_data.get("approved_by"),
        "review_assignment": review_assignment_payload(run_data),
        "approval_status": approval_status,
        "latest_approval": approval_data,
    }


def review_assignment_payload(record: dict[str, Any] | None) -> dict[str, Any]:
    data = record or {}
    claimed_by = text_value(data.get("review_claimed_by"))
    claimed_at = data.get("review_claimed_at")
    return {
        "claimed": bool(claimed_by),
        "claimed_by": claimed_by,
        "claimed_at": claimed_at,
    }


def update_run_summary(run_id: str, summary: dict[str, Any]) -> dict[str, Any]:
    from .access_scope import guard_run
    guard_run(run_id)
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                update strategyos_runs
                set finding_count = %s,
                    locked_finding_count = %s,
                    total_recoverable_sar = %s,
                    status = %s,
                    current_stage = %s,
                    requires_human_review = %s,
                    approved_at = %s,
                    approved_by = %s,
                    summary_json = %s::jsonb
                where id = %s
                returning id, created_at, status, current_stage, requires_human_review, approved_at, approved_by, summary_json
                """,
                (
                    int(summary.get("findings", 0)),
                    int(summary.get("locked_findings", 0)),
                    money_value(summary.get("total_recoverable_sar")) or 0.0,
                    text_value(summary.get("status")) or "completed",
                    text_value(summary.get("current_stage")) or "completed",
                    bool(summary.get("requires_human_review", False)),
                    summary.get("approved_at"),
                    summary.get("approved_by"),
                    json_blob(summary),
                    run_id,
                ),
            )
            record = fetchone_dict(cur)
        conn.commit()
    if record is None:
        return {"status": "missing", "run_id": run_id}
    normalized = normalize_record(record)
    normalized["run_id"] = normalized.pop("id")
    return normalized


def persist_run_summary(
    summary: dict[str, Any],
    *,
    run_id: str | None = None,
    bundle: DataBundle | None = None,
    findings: list[Finding] | None = None,
    artifacts: dict[str, Path] | None = None,
    audit_events: list[AuditEvent] | None = None,
) -> dict[str, Any]:
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped
    assert connection is not None

    findings = findings or []
    artifacts = artifacts or {}
    audit_events = audit_events or []

    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            tenant_id = upsert_tenant(cur)
            source_system_id = upsert_source_system(cur, tenant_id, summary=summary)
            persisted_run_id = upsert_run_summary(cur, summary, run_id=run_id)
            counts: dict[str, int] = {}
            if bundle is not None:
                batch_id = insert_ingestion_batch(
                    cur, tenant_id, source_system_id, persisted_run_id, summary, bundle
                )
                evidence_ids = persist_evidence_documents(
                    cur, tenant_id, source_system_id, batch_id, bundle, summary
                )
                counts.update(
                    persist_finance_records(
                        cur,
                        tenant_id,
                        batch_id,
                        evidence_ids,
                        bundle,
                        run_id=persisted_run_id,
                        summary=summary,
                    )
                )
                counts["evidence_documents"] = len(evidence_ids)
                counts["findings"] = persist_findings(cur, persisted_run_id, findings)
                counts["citations"] = persist_citations(
                    cur, persisted_run_id, evidence_ids, bundle, findings
                )
                counts["audit_events"] = persist_audit_events(
                    cur, persisted_run_id, audit_events
                )
                counts.update(
                    persist_knowledge_graph(
                        cur,
                        tenant_id,
                        persisted_run_id,
                        artifacts.get("knowledge_graph"),
                    )
                )
            counts["artifacts"] = persist_artifacts(
                cur, persisted_run_id, artifacts, summary
            )
        conn.commit()
    return {
        "status": "persisted",
        "run_id": str(persisted_run_id),
        "data_management": counts,
    }


def data_management_status(run_id: str | None = None) -> dict[str, Any]:
    normalized_run_id = uuid_value(run_id) if run_id is not None else None
    if run_id is not None and normalized_run_id is None:
        return {
            "status": "invalid_run_id",
            "reason": "Database backing status is unavailable for this public run reference.",
        }
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped
    assert connection is not None

    try:
        with connection as conn:
            ensure_data_schema(conn)
            with conn.cursor() as cur:
                if run_id is None:
                    cur.execute(
                        "select id from strategyos_runs order by created_at desc limit 1"
                    )
                    row = cur.fetchone()
                    if row is None:
                        return {
                            "status": "missing",
                            "reason": "No StrategyOS run has been persisted.",
                        }
                    normalized_run_id = uuid_value(row[0])
                    run_id = str(normalized_run_id or row[0])
                else:
                    run_id = normalized_run_id
                cur.execute(
                    """
                    select ib.id, t.id, t.slug, ss.name, ib.dataset_root
                    from strategyos_ingestion_batches ib
                    join strategyos_tenants t on t.id = ib.tenant_id
                    join strategyos_source_systems ss on ss.id = ib.source_system_id
                    where ib.run_id = %s
                    order by ib.completed_at desc
                    limit 1
                    """,
                    (normalized_run_id,),
                )
                batch = cur.fetchone()
                if batch is None:
                    return {
                        "status": "missing",
                        "run_id": run_id,
                        "reason": "No data-management batch for this run.",
                    }
                batch_id, tenant_id, tenant_slug, source_system_name, dataset_root = batch
                counts = {
                    "evidence_documents": count_for(
                        cur,
                        "strategyos_ingestion_batch_documents",
                        "batch_id",
                        batch_id,
                    ),
                    "finance_entities": count_for(
                        cur, "strategyos_finance_entities", "batch_id", batch_id
                    ),
                    "finance_transactions": count_for(
                        cur, "strategyos_finance_transactions", "batch_id", batch_id
                    ),
                    "finance_balances": count_for(
                        cur, "strategyos_finance_balances", "batch_id", batch_id
                    ),
                    "findings": count_for(cur, "strategyos_findings", "run_id", run_id),
                    "citations": count_for(
                        cur, "strategyos_finding_citations", "run_id", run_id
                    ),
                    "artifacts": count_for(
                        cur, "strategyos_artifacts", "run_id", run_id
                    ),
                    "audit_events": count_for(
                        cur, "strategyos_agent_events", "run_id", run_id
                    ),
                    "kg_nodes": count_for(cur, "strategyos_kg_nodes", "run_id", run_id),
                    "kg_edges": count_for(cur, "strategyos_kg_edges", "run_id", run_id),
                    "tenant_profiles": count_for(
                        cur, "strategyos_tenant_profiles", "tenant_id", tenant_id
                    ),
                    "tenant_profile_versions": count_profile_versions_for_tenant(
                        cur, tenant_id
                    ),
                    "canonical_finance_entities": count_for(
                        cur,
                        "strategyos_canonical_finance_entities",
                        "tenant_id",
                        tenant_id,
                    ),
                    "canonical_finance_entity_links": count_for(
                        cur,
                        "strategyos_canonical_finance_entity_links",
                        "tenant_id",
                        tenant_id,
                    ),
                    "fx_rates": count_for(
                        cur, "strategyos_fx_rates", "tenant_id", tenant_id
                    ),
                    "backfill_runs": count_for(
                        cur, "strategyos_backfill_runs", "tenant_id", tenant_id
                    ),
                    "cutover_metrics": count_for(
                        cur, "strategyos_cutover_metrics", "tenant_id", tenant_id
                    ),
                }
                artifact_paths = artifact_paths_for_run(cur, run_id)
                return {
                    "status": "ready",
                    "run_id": run_id,
                    "batch_id": str(batch_id),
                    "tenant_id": str(tenant_id),
                    "tenant": tenant_slug,
                    "source_system": source_system_name,
                    "dataset_root": dataset_root,
                    "counts": counts,
                    "artifacts": artifact_paths,
                }
    except Exception:
        return {
            "status": "failed",
            "reason": "Database backing status is temporarily unavailable.",
        }


def ensure_data_schema(conn: Any) -> None:
    cache_key = _schema_database_key(conn)
    if cache_key is not None and cache_key in _SCHEMA_READY_DATABASES:
        return
    with _SCHEMA_READY_LOCK:
        if cache_key is not None and cache_key in _SCHEMA_READY_DATABASES:
            return
        sql = schema_path().read_text(encoding="utf-8")
        with conn.cursor() as cur:
            _execute_sql_statements(cur, sql)
            apply_schema_migrations(cur)
        conn.commit()
        if cache_key is not None:
            _SCHEMA_READY_DATABASES.add(cache_key)


def _schema_database_key(conn: Any) -> tuple[str, str, str, str] | None:
    """Identify a real PostgreSQL database without caching test doubles.

    The application applies the additive schema during startup. Re-running the
    full DDL contract on every request can block ordinary reads behind a long
    ingestion transaction, so successful initialization is cached per process
    and physical database. Lightweight test doubles intentionally have no
    psycopg ``info`` object and retain the uncached validation path.
    """
    info = getattr(conn, "info", None)
    if info is None:
        return None
    database = str(getattr(info, "dbname", "") or "").strip()
    if not database:
        return None
    return (
        str(getattr(info, "host", "") or ""),
        str(getattr(info, "port", "") or ""),
        database,
        str(getattr(info, "user", "") or ""),
    )


def _execute_sql_statements(cur: Any, sql: str) -> None:
    for statement in sql.split(";"):
        statement = statement.strip()
        if statement:
            cur.execute(statement)


def migration_path() -> Path:
    return schema_path().parent / "migrations"


def apply_schema_migrations(cur: Any) -> list[str]:
    """Apply immutable, checksummed migrations under one transaction lock."""
    root = migration_path()
    if not root.is_dir():
        return []
    cur.execute("select pg_advisory_xact_lock(68371429)")
    applied: list[str] = []
    for path in sorted(root.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        version = path.stem.split("_", 1)[0]
        payload = path.read_bytes()
        checksum = hashlib.sha256(payload).hexdigest()
        cur.execute(
            "select checksum_sha256 from strategyos_schema_migrations where version = %s",
            (version,),
        )
        row = cur.fetchone()
        if row is not None:
            if str(row[0]) != checksum:
                raise RuntimeError(
                    f"Applied schema migration {version} no longer matches its recorded checksum."
                )
            continue
        _execute_sql_statements(cur, payload.decode("utf-8"))
        cur.execute(
            """
            insert into strategyos_schema_migrations (version, checksum_sha256)
            values (%s, %s)
            """,
            (version, checksum),
        )
        applied.append(version)
    return applied


def upsert_tenant(cur: Any) -> str:
    cur.execute(
        """
        insert into strategyos_tenants (slug, display_name)
        values (%s, %s)
        on conflict (slug) do update set display_name = excluded.display_name
        returning id
        """,
        (CONFIG.tenant_slug, CONFIG.tenant_name),
    )
    return cur.fetchone()[0]


def upsert_source_system(
    cur: Any, tenant_id: str, *, summary: dict[str, Any] | None = None
) -> str:
    source_pack = dict((summary or {}).get("source_pack") or {})
    source_contract = dict(
        source_pack.get("source_contract")
        or (summary or {}).get("source_contract")
        or {}
    )
    if source_contract:
        source_key = text_value(source_contract.get("source_key")) or "unclassified-source"
        display_name = text_value(source_contract.get("display_name")) or "Unclassified source pack"
        origin_category = text_value(source_contract.get("origin_category")) or "unknown"
        capture_method = text_value(source_contract.get("capture_method")) or "unknown"
        cur.execute(
            """
            insert into strategyos_source_systems
                (tenant_id, name, system_type, source_key, origin_category, capture_method,
                 governed_owner, provider_name, authorization_basis, license_policy_ref, metadata)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            on conflict (tenant_id, source_key) do update set
                name = excluded.name,
                origin_category = excluded.origin_category,
                capture_method = excluded.capture_method,
                governed_owner = excluded.governed_owner,
                provider_name = excluded.provider_name,
                authorization_basis = excluded.authorization_basis,
                license_policy_ref = excluded.license_policy_ref,
                metadata = excluded.metadata,
                status = 'active'
            returning id
            """,
            (
                tenant_id,
                display_name,
                f"source_pack:{source_key}",
                source_key,
                origin_category,
                capture_method,
                source_contract.get("governed_owner"),
                source_contract.get("provider_name"),
                source_contract.get("authorization_basis"),
                source_contract.get("license_policy_ref"),
                json_blob(
                    {
                        "classification_status": source_contract.get(
                            "classification_status"
                        ),
                        "confirmed_by": source_contract.get("confirmed_by"),
                        "confirmed_at": source_contract.get("confirmed_at"),
                    }
                ),
            ),
        )
        source_system_id = cur.fetchone()[0]
        persist_source_registration_version(
            cur,
            tenant_id=tenant_id,
            source_system_id=source_system_id,
            source=SourceRegistration(
                tenant_id=str(tenant_id),
                source_key=source_key,
                display_name=display_name,
                origin_category=origin_category,
                capture_method=capture_method,
                governed_owner=source_contract.get("governed_owner"),
                provider_name=source_contract.get("provider_name"),
                authorization_basis=source_contract.get("authorization_basis"),
                license_policy_ref=source_contract.get("license_policy_ref"),
                metadata={
                    "classification_status": source_contract.get(
                        "classification_status"
                    )
                },
            ),
            recorded_by=text_value(source_contract.get("confirmed_by")) or "system",
            rationale="Source-pack registration received by governed ingestion.",
        )
        access_policy = source_contract.get("access_policy")
        if source_contract.get("classification_status") == "confirmed" and isinstance(
            access_policy, dict
        ):
            persist_source_access_policy(
                cur,
                tenant_id=tenant_id,
                source_system_id=source_system_id,
                source_key=source_key,
                policy_payload=access_policy,
                recorded_by=text_value(source_contract.get("confirmed_by"))
                or "operator",
                rationale="Operator-confirmed source-pack access contract.",
            )
        return source_system_id
    source_key = "internal-finance-dataset"
    legacy_policy_roles = [
        "tenant_admin",
        "system",
        "operator",
        "reviewer",
        "analyst",
        "auditor",
        "executive",
        "bu",
    ]
    legacy_policy_purposes = [
        "operations",
        "executive_briefing",
        "analysis",
        "scenario",
        "export",
    ]
    legacy_policy_fingerprint = stable_key(
        "source-policy",
        source_key,
        sorted(legacy_policy_roles),
        sorted(legacy_policy_purposes),
        [],
        True,
        False,
        False,
    )
    cur.execute(
        """
        insert into strategyos_source_systems
            (tenant_id, name, system_type, source_key, origin_category, capture_method,
             governed_owner, authorization_basis)
        values (%s, %s, %s, %s, 'internal_system', 'folder_import', 'tenant_operator',
                'Existing authenticated StrategyOS finance dataset intake')
        on conflict (tenant_id, name, system_type) do update set
            status = 'active',
            source_key = excluded.source_key,
            origin_category = excluded.origin_category,
            capture_method = excluded.capture_method,
            governed_owner = excluded.governed_owner,
            authorization_basis = excluded.authorization_basis
        returning id
        """,
        (tenant_id, CONFIG.source_system_name, "finance_dataset", source_key),
    )
    source_system_id = cur.fetchone()[0]
    persist_source_registration_version(
        cur,
        tenant_id=tenant_id,
        source_system_id=source_system_id,
        source=SourceRegistration(
            tenant_id=str(tenant_id),
            source_key=source_key,
            display_name=CONFIG.source_system_name,
            origin_category="internal_system",
            capture_method="folder_import",
            governed_owner="tenant_operator",
            authorization_basis="Existing authenticated StrategyOS finance dataset intake",
        ),
        recorded_by="system:migration",
        rationale="Legacy source registered for shadow-claim compatibility.",
    )
    cur.execute(
        """
        insert into strategyos_source_access_policies
            (tenant_id, source_system_id, policy_version, policy_fingerprint,
             allowed_roles, allowed_purposes,
             export_allowed, external_model_allowed, quote_allowed, recorded_by, rationale)
        values (%s, %s, 1, %s, %s, %s,
                true, false, false, 'system:migration',
                'Legacy-parity policy; external-model use remains denied until explicitly authorized.')
        on conflict (source_system_id, policy_version) do nothing
        """,
        (
            tenant_id,
            source_system_id,
            legacy_policy_fingerprint,
            legacy_policy_roles,
            legacy_policy_purposes,
        ),
    )
    return source_system_id


def persist_source_access_policy(
    cur: Any,
    *,
    tenant_id: str,
    source_system_id: str,
    source_key: str,
    policy_payload: dict[str, Any],
    recorded_by: str,
    rationale: str,
) -> int:
    policy = SourceAccessPolicy(
        source_key=source_key,
        allowed_roles=frozenset(policy_payload.get("allowed_roles") or []),
        allowed_purposes=frozenset(policy_payload.get("allowed_purposes") or []),
        allowed_business_units=frozenset(
            policy_payload.get("allowed_business_units") or []
        ),
        export_allowed=bool(policy_payload.get("export_allowed", False)),
        external_model_allowed=bool(
            policy_payload.get("external_model_allowed", False)
        ),
        quote_allowed=bool(policy_payload.get("quote_allowed", False)),
    )
    cur.execute(
        """
        select policy_version from strategyos_source_access_policies
        where source_system_id = %s and policy_fingerprint = %s
        """,
        (source_system_id, policy.fingerprint),
    )
    existing = cur.fetchone()
    if existing is not None:
        return int(existing[0])
    cur.execute(
        "select coalesce(max(policy_version), 0) from strategyos_source_access_policies where source_system_id = %s",
        (source_system_id,),
    )
    version = int(cur.fetchone()[0]) + 1
    cur.execute(
        "update strategyos_source_access_policies set effective_to = now() where source_system_id = %s and effective_to is null",
        (source_system_id,),
    )
    cur.execute(
        """
        insert into strategyos_source_access_policies
            (tenant_id, source_system_id, policy_version, policy_fingerprint,
             allowed_roles, allowed_purposes, allowed_business_units, export_allowed,
             external_model_allowed, quote_allowed, recorded_by, rationale)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            tenant_id,
            source_system_id,
            version,
            policy.fingerprint,
            sorted(policy.allowed_roles),
            sorted(str(item) for item in policy.allowed_purposes),
            sorted(policy.allowed_business_units),
            policy.export_allowed,
            policy.external_model_allowed,
            policy.quote_allowed,
            recorded_by,
            rationale,
        ),
    )
    return version


def persist_source_registration_version(
    cur: Any,
    *,
    tenant_id: str,
    source_system_id: str,
    source: SourceRegistration,
    recorded_by: str,
    rationale: str,
) -> int:
    cur.execute(
        """
        select registration_version
        from strategyos_source_registration_versions
        where source_system_id = %s and registration_fingerprint = %s
        """,
        (source_system_id, source.fingerprint),
    )
    existing = cur.fetchone()
    if existing is not None:
        return int(existing[0])
    cur.execute(
        "select coalesce(max(registration_version), 0) from strategyos_source_registration_versions where source_system_id = %s",
        (source_system_id,),
    )
    version = int(cur.fetchone()[0]) + 1
    cur.execute(
        "update strategyos_source_registration_versions set effective_to = now() where source_system_id = %s and effective_to is null",
        (source_system_id,),
    )
    cur.execute(
        """
        insert into strategyos_source_registration_versions
            (tenant_id, source_system_id, registration_version, registration_fingerprint,
             display_name, origin_category, capture_method, governed_owner, provider_name,
             authorization_basis, license_policy_ref, retention_class, sensitivity_class,
             metadata, recorded_by, rationale)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
        """,
        (
            tenant_id,
            source_system_id,
            version,
            source.fingerprint,
            source.display_name,
            source.origin_category,
            source.capture_method,
            source.governed_owner,
            source.provider_name,
            source.authorization_basis,
            source.license_policy_ref,
            source.retention_class,
            source.sensitivity_class,
            json_blob(dict(source.metadata)),
            recorded_by,
            rationale,
        ),
    )
    return version


def upsert_run_summary(
    cur: Any, summary: dict[str, Any], *, run_id: str | None = None
) -> str:
    if run_id is not None:
        cur.execute(
            """
            update strategyos_runs
            set run_dir = %s,
                dataset_root = %s,
                finding_count = %s,
                locked_finding_count = %s,
                total_recoverable_sar = %s,
                status = %s,
                current_stage = %s,
                requires_human_review = %s,
                approved_at = %s,
                approved_by = %s,
                summary_json = %s::jsonb
            where id = %s
            returning id
            """,
            (
                summary["run_dir"],
                summary["dataset"],
                summary["findings"],
                summary["locked_findings"],
                summary["total_recoverable_sar"],
                summary.get("status", "completed"),
                summary.get("current_stage", "completed"),
                bool(summary.get("requires_human_review", False)),
                summary.get("approved_at"),
                summary.get("approved_by"),
                json_blob(summary),
                run_id,
            ),
        )
        row = cur.fetchone()
        if row is not None:
            return row[0]
    return insert_run_summary(cur, summary)


def insert_run_summary(cur: Any, summary: dict[str, Any]) -> str:
    cur.execute(
        """
        insert into strategyos_runs
            (run_dir, dataset_root, finding_count, locked_finding_count, total_recoverable_sar,
             status, current_stage, requires_human_review, approved_at, approved_by, summary_json, tenant_key, business_unit_scope)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb)
        returning id
        """,
        (
            summary["run_dir"],
            summary["dataset"],
            summary["findings"],
            summary["locked_findings"],
            summary["total_recoverable_sar"],
            summary.get("status", "completed"),
            summary.get("current_stage", "completed"),
            bool(summary.get("requires_human_review", False)),
            summary.get("approved_at"),
            summary.get("approved_by"),
            json_blob(summary),
            CONFIG.tenant_slug,
            json_blob(summary.get("business_units") or []),
        ),
    )
    return cur.fetchone()[0]


def insert_ingestion_batch(
    cur: Any,
    tenant_id: str,
    source_system_id: str,
    run_id: str,
    summary: dict[str, Any],
    bundle: DataBundle,
) -> str:
    cur.execute(
        """
        insert into strategyos_ingestion_batches
            (tenant_id, source_system_id, run_id, batch_label, dataset_root, manifest_json)
        values (%s, %s, %s, %s, %s, %s::jsonb)
        returning id
        """,
        (
            tenant_id,
            source_system_id,
            run_id,
            Path(summary["run_dir"]).name,
            str(bundle.dataset_root),
            json_blob(bundle.evidence.manifest),
        ),
    )
    return cur.fetchone()[0]


def persist_evidence_documents(
    cur: Any,
    tenant_id: str,
    source_system_id: str,
    batch_id: str,
    bundle: DataBundle,
    summary: dict[str, Any],
) -> dict[str, str]:
    source_uri_map = {
        Path(item.get("path", "")).name: item.get("uri")
        for item in summary.get("source_uploads", [])
    }
    evidence_ids: dict[str, str] = {}
    cur.execute(
        "select source_key from strategyos_source_systems where id = %s and tenant_id = %s",
        (source_system_id, tenant_id),
    )
    source_system_row = cur.fetchone()
    if source_system_row is None:
        raise RuntimeError("Ingestion source registration was not found.")
    source_key = str(source_system_row[0])
    for rel_path, manifest in bundle.evidence.manifest.items():
        object_uri = source_uri_map.get(Path(rel_path).name)
        cur.execute(
            """
            insert into strategyos_evidence_documents
                (tenant_id, source_system_id, source_path, source_group, file_name, media_type, size_bytes,
                 source_hash, source_uri, object_uri, ocr_status, manifest_json)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
            on conflict (tenant_id, source_hash) do update set
                last_seen_at = now(),
                object_uri = coalesce(excluded.object_uri, strategyos_evidence_documents.object_uri),
                ocr_status = excluded.ocr_status,
                manifest_json = excluded.manifest_json
            returning id
            """,
            (
                tenant_id,
                source_system_id,
                rel_path,
                manifest.get("source_group", Path(rel_path).parent.name),
                Path(rel_path).name,
                media_type_for(rel_path),
                manifest.get("size_bytes", 0),
                manifest["sha256"],
                f"dataset://{rel_path}",
                object_uri,
                json_blob(bundle.evidence.ocr_status.get(rel_path, {})),
                json_blob(manifest),
            ),
        )
        evidence_id = cur.fetchone()[0]
        evidence_ids[rel_path] = evidence_id
        received_at = manifest.get("ingested_at") or datetime.now(UTC)
        occurrence_key = stable_key(
            "occurrence",
            tenant_id,
            source_key,
            rel_path,
            manifest["sha256"],
        )
        cur.execute(
            """
            insert into strategyos_evidence_occurrences
                (tenant_id, source_system_id, evidence_document_id, ingestion_batch_id,
                 occurrence_key, source_native_id, source_native_version, original_uri,
                 received_at, metadata)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            on conflict (tenant_id, occurrence_key) do nothing
            """,
            (
                tenant_id,
                source_system_id,
                evidence_id,
                batch_id,
                occurrence_key,
                rel_path,
                manifest["sha256"],
                f"dataset://{rel_path}",
                received_at,
                json_blob(
                    {
                        "source_disposition": manifest.get("source_disposition"),
                        "classification": manifest.get("classification"),
                    }
                ),
            ),
        )
        cur.execute(
            """
            insert into strategyos_ingestion_batch_documents (batch_id, evidence_document_id)
            values (%s, %s)
            on conflict do nothing
            """,
            (batch_id, evidence_id),
        )
    return evidence_ids


def persist_finance_records(
    cur: Any,
    tenant_id: str,
    batch_id: str,
    evidence_ids: dict[str, str],
    bundle: DataBundle,
    *,
    run_id: str,
    summary: dict[str, Any],
) -> dict[str, int]:
    counts = {
        "finance_entities": 0,
        "finance_transactions": 0,
        "finance_balances": 0,
        "canonical_claim_revisions": 0,
        "canonical_claim_exceptions": 0,
        "canonical_analysis_snapshots": 0,
        "canonical_reconciliations": 0,
    }
    counts["finance_entities"] += persist_entities(
        cur,
        tenant_id,
        batch_id,
        evidence_ids.get("03_Master_Data/Vendor_Master.xlsx"),
        "vendor",
        bundle.vendors,
        "Vendor_ID",
        "Vendor_Name",
    )
    counts["finance_entities"] += persist_entities(
        cur,
        tenant_id,
        batch_id,
        evidence_ids.get("03_Master_Data/Customer_Master.xlsx"),
        "customer",
        bundle.customers,
        "Customer_ID",
        "Customer_Name",
    )
    counts["finance_transactions"] += persist_transactions(
        cur,
        tenant_id,
        batch_id,
        evidence_ids.get("02_ERP_Extracts/AP_Invoices_H1_2026.xlsx"),
        "ap_invoice",
        bundle.ap,
        "Invoice_ID",
        "Vendor_ID",
        "Invoice_Date",
        "Due_Date",
        "Payment_Date",
        "Amount_SAR",
        "Currency",
        "Status",
    )
    counts["finance_transactions"] += persist_transactions(
        cur,
        tenant_id,
        batch_id,
        evidence_ids.get("02_ERP_Extracts/AR_Invoices_H1_2026.xlsx"),
        "ar_invoice",
        bundle.ar,
        "Invoice_ID",
        "Customer_ID",
        "Invoice_Date",
        "Due_Date",
        "Collection_Date",
        "Amount_SAR",
        None,
        "Status",
    )
    counts["finance_transactions"] += persist_transactions(
        cur,
        tenant_id,
        batch_id,
        evidence_ids.get("05_Purchase_Orders/PO_Log_H1_2026.csv"),
        "purchase_order",
        bundle.po,
        "PO_ID",
        "Vendor_ID",
        "PO_Date",
        None,
        "Delivery_Date",
        "Total",
        "Currency",
        "Status",
    )
    counts["finance_transactions"] += persist_transactions(
        cur,
        tenant_id,
        batch_id,
        evidence_ids.get("02_ERP_Extracts/GL_Extract_H1_2026.csv"),
        "gl_entry",
        bundle.gl,
        "Reference",
        "Account",
        "Date",
        None,
        None,
        None,
        None,
        None,
    )
    trial_balance_counts = persist_trial_balance(
        cur,
        tenant_id,
        batch_id,
        evidence_ids.get("02_ERP_Extracts/Trial_Balance_June_2026.xlsx"),
        bundle,
    )
    counts["finance_balances"] += trial_balance_counts["records"]
    counts["canonical_claim_revisions"] += trial_balance_counts["claims"]
    cash_forecast_counts = persist_cash_forecast(
        cur, tenant_id, batch_id, evidence_ids, bundle
    )
    counts["finance_balances"] += cash_forecast_counts["records"]
    counts["canonical_claim_revisions"] += cash_forecast_counts["claims"]
    transaction_claims = persist_transaction_claims(
        cur,
        tenant_id=tenant_id,
        batch_id=batch_id,
        run_id=run_id,
    )
    counts["canonical_claim_revisions"] += transaction_claims["claims"]
    counts["canonical_claim_exceptions"] += transaction_claims["exceptions"]
    kpi_claims = persist_finance_kpi_claims(
        cur,
        tenant_id=tenant_id,
        batch_id=batch_id,
        run_id=run_id,
        evidence_ids=evidence_ids,
        finance_payload=dict(summary.get("finance_kpi") or {}),
        recorded_at=summary.get("created_at"),
    )
    counts["canonical_claim_revisions"] += kpi_claims["claims"]
    counts["canonical_claim_exceptions"] += kpi_claims["exceptions"]
    snapshot_count = persist_run_claim_snapshot(
        cur,
        tenant_id=tenant_id,
        batch_id=batch_id,
        run_id=run_id,
        as_of_at=summary.get("created_at"),
    )
    counts["canonical_analysis_snapshots"] += snapshot_count
    counts["canonical_reconciliations"] += persist_claim_reconciliation(
        cur,
        tenant_id=tenant_id,
        batch_id=batch_id,
        run_id=run_id,
    )
    return counts


def persist_oracle_canonical_snapshot(
    snapshot: OracleCanonicalSnapshot,
    *,
    tenant_id: str,
    batch_id: str | None = None,
    source_system_id: str | None = None,
) -> dict[str, Any]:
    connection, skipped = database_connection()
    if skipped is not None:
        return {
            **skipped,
            "tenant_id": tenant_id,
            "batch_id": batch_id,
            "source_system_id": source_system_id,
            "connector_mappings": len(snapshot.connector_mappings),
            "periods": len(snapshot.periods),
            "facts": len(snapshot.facts),
            "fx_rates": len(snapshot.fx_rates),
            "manual_inputs": len(snapshot.manual_inputs),
        }

    counts = {
        "connector_mappings": 0,
        "periods": 0,
        "facts": 0,
        "fx_rates": 0,
        "manual_inputs": 0,
    }
    assert connection is not None
    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            for mapping in snapshot.connector_mappings:
                cur.execute(
                    """
                    insert into strategyos_oracle_connector_mappings
                        (tenant_id, source_system_id, module, mapping_type, source_table, source_field,
                         target_field, required, notes, attributes)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    on conflict (tenant_id, module, mapping_type, source_table, source_field, target_field)
                    do update set
                        required = excluded.required,
                        notes = excluded.notes,
                        attributes = excluded.attributes
                    """,
                    (
                        tenant_id,
                        source_system_id,
                        mapping.get("module"),
                        mapping.get("mapping_type"),
                        mapping.get("source_table") or "",
                        mapping.get("source_field") or "",
                        mapping.get("target_field"),
                        bool(mapping.get("required", False)),
                        mapping.get("notes"),
                        json_blob(mapping.get("attributes", {})),
                    ),
                )
                counts["connector_mappings"] += 1

            for period in snapshot.periods:
                cur.execute(
                    """
                    insert into strategyos_finance_periods
                        (tenant_id, period_key, period_label, cadence, period_start, period_end,
                         source_period_name, attributes)
                    values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    on conflict (tenant_id, period_key, cadence) do update set
                        period_label = excluded.period_label,
                        period_start = excluded.period_start,
                        period_end = excluded.period_end,
                        source_period_name = excluded.source_period_name,
                        attributes = excluded.attributes
                    """,
                    (
                        tenant_id,
                        period.period_key,
                        period.label,
                        period.cadence,
                        period.period_start,
                        period.period_end,
                        period.source_period_name,
                        json_blob(period.attributes),
                    ),
                )
                counts["periods"] += 1

            for fact in snapshot.facts:
                cur.execute(
                    """
                    insert into strategyos_finance_facts
                        (tenant_id, batch_id, source_system_id, module, fact_type, natural_key, period_key,
                         cadence, bu_code, cost_centre, account_code, amount_value, currency,
                         reporting_currency, source_locator, attributes)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    on conflict (tenant_id, module, fact_type, natural_key) do update set
                        period_key = excluded.period_key,
                        cadence = excluded.cadence,
                        bu_code = excluded.bu_code,
                        cost_centre = excluded.cost_centre,
                        account_code = excluded.account_code,
                        amount_value = excluded.amount_value,
                        currency = excluded.currency,
                        reporting_currency = excluded.reporting_currency,
                        source_locator = excluded.source_locator,
                        attributes = excluded.attributes
                    """,
                    (
                        tenant_id,
                        batch_id,
                        source_system_id,
                        fact.module,
                        fact.fact_type,
                        fact.natural_key,
                        fact.period_key,
                        fact.cadence,
                        fact.bu_code,
                        fact.cost_centre,
                        fact.account_code,
                        money_value(fact.amount_value),
                        fact.currency,
                        fact.reporting_currency,
                        fact.source_reference,
                        json_blob(fact.attributes),
                    ),
                )
                counts["facts"] += 1

            for rate in snapshot.fx_rates:
                cur.execute(
                    """
                    insert into strategyos_fx_rates
                        (tenant_id, source_currency, reporting_currency, rate_source, rate_date,
                         rate_value, fallback_allowed, attributes)
                    values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    on conflict (tenant_id, source_currency, reporting_currency, rate_source, rate_date)
                    do update set
                        rate_value = excluded.rate_value,
                        fallback_allowed = excluded.fallback_allowed,
                        attributes = excluded.attributes
                    """,
                    (
                        tenant_id,
                        rate.source_currency,
                        rate.reporting_currency,
                        rate.rate_source,
                        rate.rate_date,
                        rate.rate_value,
                        rate.fallback_allowed,
                        json_blob(rate.attributes),
                    ),
                )
                counts["fx_rates"] += 1

            for record in snapshot.manual_inputs:
                cur.execute(
                    """
                    insert into strategyos_finance_manual_inputs
                        (tenant_id, batch_id, input_key, input_type, input_name, storage_kind,
                         cadence, period_key, owner_role, source_uri, status, attributes)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    on conflict (tenant_id, input_key) do update set
                        input_type = excluded.input_type,
                        input_name = excluded.input_name,
                        storage_kind = excluded.storage_kind,
                        cadence = excluded.cadence,
                        period_key = excluded.period_key,
                        owner_role = excluded.owner_role,
                        source_uri = excluded.source_uri,
                        status = excluded.status,
                        attributes = excluded.attributes
                    """,
                    (
                        tenant_id,
                        batch_id,
                        record.input_key,
                        record.input_type,
                        record.input_name,
                        record.storage_kind,
                        record.cadence,
                        record.period_key,
                        record.owner_role,
                        record.source_uri,
                        record.status,
                        json_blob(record.attributes),
                    ),
                )
                counts["manual_inputs"] += 1
        conn.commit()
    return {
        "status": "ok",
        "tenant_id": tenant_id,
        "batch_id": batch_id,
        "source_system_id": source_system_id,
        **counts,
    }


def persist_entities(
    cur: Any,
    tenant_id: str,
    batch_id: str,
    source_document_id: str | None,
    entity_type: str,
    df: Any,
    key_column: str,
    display_column: str,
) -> int:
    count = 0
    for idx, row in df.iterrows():
        natural_key = text_value(row.get(key_column)) or f"{entity_type}:{idx}"
        cur.execute(
            """
            insert into strategyos_finance_entities
                (tenant_id, batch_id, entity_type, natural_key, display_name, source_document_id, source_locator, attributes)
            values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            on conflict (batch_id, entity_type, natural_key) do update set attributes = excluded.attributes
            """,
            (
                tenant_id,
                batch_id,
                entity_type,
                natural_key,
                text_value(row.get(display_column)),
                source_document_id,
                row_locator(idx),
                json_blob(row_to_dict(row)),
            ),
        )
        count += 1
    return count


def persist_transactions(
    cur: Any,
    tenant_id: str,
    batch_id: str,
    source_document_id: str | None,
    transaction_type: str,
    df: Any,
    key_column: str,
    counterparty_column: str | None,
    event_date_column: str | None,
    due_date_column: str | None,
    settled_date_column: str | None,
    amount_column: str | None,
    currency_column: str | None,
    status_column: str | None,
) -> int:
    count = 0
    for idx, row in df.iterrows():
        natural_key = text_value(row.get(key_column)) or f"{transaction_type}:{idx}"
        natural_key = f"{natural_key}:{idx}"
        amount = (
            money_value(row.get(amount_column)) if amount_column else gl_amount(row)
        )
        cur.execute(
            """
            insert into strategyos_finance_transactions
                (tenant_id, batch_id, transaction_type, natural_key, counterparty_key, event_date, due_date, settled_date,
                 amount_sar, currency, status, source_document_id, source_locator, attributes)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            on conflict (batch_id, transaction_type, natural_key) do update set attributes = excluded.attributes
            """,
            (
                tenant_id,
                batch_id,
                transaction_type,
                natural_key,
                text_value(row.get(counterparty_column))
                if counterparty_column
                else None,
                date_value(row.get(event_date_column)) if event_date_column else None,
                date_value(row.get(due_date_column)) if due_date_column else None,
                date_value(row.get(settled_date_column))
                if settled_date_column
                else None,
                amount,
                text_value(row.get(currency_column)) if currency_column else "SAR",
                text_value(row.get(status_column)) if status_column else None,
                source_document_id,
                row_locator(idx),
                json_blob(row_to_dict(row)),
            ),
        )
        count += 1
    return count


def persist_trial_balance(
    cur: Any,
    tenant_id: str,
    batch_id: str,
    source_document_id: str | None,
    bundle: DataBundle,
) -> dict[str, int]:
    count = 0
    claim_count = 0
    for idx, row in bundle.trial_balance.iterrows():
        account = text_value(row.get("Account")) or f"trial_balance:{idx}"
        cur.execute(
            """
            insert into strategyos_finance_balances
                (tenant_id, batch_id, balance_type, natural_key, account, account_description, amount_sar,
                 source_document_id, source_locator, attributes)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            on conflict (batch_id, balance_type, natural_key) do update set attributes = excluded.attributes
            """,
            (
                tenant_id,
                batch_id,
                "trial_balance",
                account,
                account,
                text_value(row.get("Account_Description")),
                money_value(row.get("Net")),
                source_document_id,
                row_locator(idx),
                json_blob(row_to_dict(row)),
            ),
        )
        amount = money_value(row.get("Net"))
        if amount is not None:
            _claim_revision_id, created = persist_shadow_claim(
                    cur,
                    tenant_id=tenant_id,
                    batch_id=batch_id,
                    subject_type="finance_account",
                    subject_key=account,
                    metric_key="finance.trial_balance.net",
                    claim_kind=ClaimKind.ACTUAL,
                    value_numeric=amount,
                    unit="SAR",
                    currency="SAR",
                    source_document_id=source_document_id,
                    source_locator=row_locator(idx),
                    dimensions={"account": account},
                    metadata={"legacy_projection": "strategyos_finance_balances"},
                )
            claim_count += int(created)
        count += 1
    return {"records": count, "claims": claim_count}


def persist_cash_forecast(
    cur: Any,
    tenant_id: str,
    batch_id: str,
    evidence_ids: dict[str, str],
    bundle: DataBundle,
) -> dict[str, int]:
    count = 0
    claim_count = 0
    source_document_id = evidence_ids.get(
        "07_Cash_Forecast/CFO_Cash_Forecast_June_2026.xlsx"
    )
    for sheet_name, df in bundle.cash_forecast.items():
        for idx, row in df.iterrows():
            payload = row_to_dict(row) | {"sheet_name": sheet_name}
            natural_key = f"{sheet_name}:{idx}"
            amount = money_value(row.get("Balance (SAR)"))
            if amount is None:
                amount = money_value(row.get("H2_Total_LC"))
            cur.execute(
                """
                insert into strategyos_finance_balances
                    (tenant_id, batch_id, balance_type, natural_key, account, account_description, amount_sar,
                     source_document_id, source_locator, attributes)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                on conflict (batch_id, balance_type, natural_key) do update set attributes = excluded.attributes
                """,
                (
                    tenant_id,
                    batch_id,
                    "cash_forecast",
                    natural_key,
                    text_value(row.get("Account")) or sheet_name,
                    sheet_name,
                    amount,
                    source_document_id,
                    f"{sheet_name} sheet row {idx + 2}",
                    json_blob(payload),
                ),
            )
            if amount is not None:
                _claim_revision_id, created = persist_shadow_claim(
                        cur,
                        tenant_id=tenant_id,
                        batch_id=batch_id,
                        subject_type="cash_forecast_line",
                        subject_key=natural_key,
                        metric_key="finance.cash_forecast.balance",
                        claim_kind=ClaimKind.FORECAST,
                        value_numeric=amount,
                        unit="SAR",
                        currency="SAR",
                        source_document_id=source_document_id,
                        source_locator=f"{sheet_name} sheet row {idx + 2}",
                        author_identity="source-role:cfo",
                        dimensions={"sheet_name": sheet_name},
                        metadata={"legacy_projection": "strategyos_finance_balances"},
                    )
                claim_count += int(created)
            count += 1
    return {"records": count, "claims": claim_count}


def persist_shadow_claim(
    cur: Any,
    *,
    tenant_id: str,
    batch_id: str,
    subject_type: str,
    subject_key: str,
    metric_key: str,
    claim_kind: ClaimKind,
    value_numeric: Any,
    unit: str,
    currency: str | None,
    source_document_id: str | None,
    source_locator: str | None,
    author_identity: str | None = None,
    business_unit: str | None = None,
    dimensions: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    as_of_at: datetime | None = None,
    production_method: ProductionMethod = ProductionMethod.IMPORTED,
    formula_key: str | None = None,
    formula_version: str | None = None,
    input_revision_ids: tuple[str, ...] = (),
) -> tuple[str, bool]:
    """Shadow-write one immutable claim without changing existing read paths."""
    occurrence_key: str | None = None
    occurrence_id: str | None = None
    if source_document_id is not None:
        cur.execute(
            """
            select eo.id, eo.occurrence_key, ss.source_key
            from strategyos_evidence_occurrences eo
            join strategyos_source_systems ss on ss.id = eo.source_system_id
            where eo.tenant_id = %s and eo.evidence_document_id = %s and eo.ingestion_batch_id = %s
            order by eo.created_at desc
            limit 1
            """,
            (tenant_id, source_document_id, batch_id),
        )
        occurrence = cur.fetchone()
        # An identical artifact received through the same governed source is a
        # single evidence occurrence by contract.  A later ingestion batch may
        # therefore reference an occurrence first recorded by an earlier batch.
        if occurrence is None:
            cur.execute(
                """
                select eo.id, eo.occurrence_key, ss.source_key
                from strategyos_evidence_occurrences eo
                join strategyos_source_systems ss on ss.id = eo.source_system_id
                join strategyos_ingestion_batches b on b.source_system_id = ss.id
                where eo.tenant_id = %s and eo.evidence_document_id = %s
                  and b.id = %s
                order by eo.created_at desc
                limit 1
                """,
                (tenant_id, source_document_id, batch_id),
            )
            occurrence = cur.fetchone()
        if occurrence is not None:
            occurrence_id, occurrence_key, assertion_namespace = occurrence
        else:
            assertion_namespace = "unclassified-source"
    else:
        assertion_namespace = "unclassified-source"
    draft = ClaimDraft(
        tenant_id=str(tenant_id),
        assertion_namespace=str(assertion_namespace),
        subject_type=subject_type,
        subject_key=subject_key,
        metric_key=metric_key,
        claim_kind=claim_kind,
        production_method=production_method,
        value_numeric=str(value_numeric),
        unit=unit,
        currency=currency,
        business_unit=business_unit,
        dimensions=dimensions or {},
        period_start=period_start,
        period_end=period_end,
        as_of_at=as_of_at,
        author_identity=author_identity,
        source_occurrence_keys=(str(occurrence_key),) if occurrence_key else (),
        formula_key=formula_key,
        formula_version=formula_version,
        input_revision_ids=input_revision_ids,
        metadata=(metadata or {}) | {"batch_id": str(batch_id)},
    )
    cur.execute(
        """
        insert into strategyos_claim_families
            (tenant_id, family_key, assertion_namespace, claim_kind_lane,
             subject_type, subject_key, metric_key, business_unit, dimensions,
             period_start, period_end)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
        on conflict (tenant_id, family_key) do nothing
        """,
        (
            tenant_id,
            draft.family_key,
            draft.assertion_namespace,
            draft.claim_kind,
            subject_type,
            subject_key,
            metric_key,
            business_unit,
            json_blob(dimensions or {}),
            period_start,
            period_end,
        ),
    )
    cur.execute(
        "select id from strategyos_claim_families where tenant_id = %s and family_key = %s for update",
        (tenant_id, draft.family_key),
    )
    family_id = cur.fetchone()[0]
    cur.execute(
        "select id from strategyos_claim_revisions where claim_family_id = %s and fingerprint = %s",
        (family_id, draft.fingerprint),
    )
    existing_revision = cur.fetchone()
    if existing_revision is not None:
        return str(existing_revision[0]), False
    cur.execute(
        "select id, revision_number from strategyos_claim_revisions where claim_family_id = %s order by revision_number desc limit 1",
        (family_id,),
    )
    previous = cur.fetchone()
    revision_number = int(previous[1]) + 1 if previous else 1
    cur.execute(
        """
        insert into strategyos_claim_revisions
            (tenant_id, claim_family_id, revision_number, fingerprint, claim_kind,
             production_method, value_numeric, unit, scale, currency, as_of_at, author_identity,
             formula_key, formula_version, traceability_state, supersedes_revision_id, metadata)
        values (%s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        returning id
        """,
        (
            tenant_id,
            family_id,
            revision_number,
            draft.fingerprint,
            draft.claim_kind,
            draft.production_method,
            draft.value_numeric,
            draft.unit,
            draft.currency,
            draft.as_of_at,
            draft.author_identity,
            draft.formula_key,
            draft.formula_version,
            "present" if occurrence_id or draft.input_revision_ids else "incomplete",
            previous[0] if previous else None,
            json_blob(dict(draft.metadata) | {"source_locator": source_locator}),
        ),
    )
    revision_id = cur.fetchone()[0]
    if occurrence_id is not None:
        cur.execute(
            """
            insert into strategyos_claim_evidence_links
                (claim_revision_id, evidence_occurrence_id, relationship_type, source_locator)
            values (%s, %s, 'supports', %s)
            """,
            (revision_id, occurrence_id, source_locator),
        )
    for input_revision_id in draft.input_revision_ids:
        cur.execute(
            "select claim_kind from strategyos_claim_revisions where id = %s and tenant_id = %s",
            (input_revision_id, tenant_id),
        )
        input_record = cur.fetchone()
        if input_record is None:
            raise ValueError("Calculated claim input must exist in the same tenant.")
        if draft.claim_kind == ClaimKind.ACTUAL and input_record[0] != ClaimKind.ACTUAL:
            raise ValueError("Calculated actuals require actual inputs.")
        cur.execute(
            """
            insert into strategyos_claim_dependencies
                (derived_claim_revision_id, input_claim_revision_id, input_role)
            values (%s, %s, 'input')
            on conflict do nothing
            """,
            (revision_id, input_revision_id),
        )
    for projection in ("graph", "vector", "cache"):
        cur.execute(
            """
            insert into strategyos_claim_projection_outbox
                (tenant_id, claim_revision_id, projection_type, operation, payload, idempotency_key)
            values (%s, %s, %s, 'upsert', %s::jsonb, %s)
            on conflict do nothing
            """,
            (
                tenant_id,
                revision_id,
                projection,
                json_blob({"claim_revision_id": str(revision_id), "family_key": draft.family_key}),
                f"claim:{revision_id}:upsert",
            ),
        )
    return str(revision_id), True


def _record_claim_backfill_exception(
    cur: Any,
    *,
    tenant_id: str,
    run_id: str,
    batch_id: str,
    record_type: str,
    record_key: str,
    reason_code: str,
    detail: str,
    evidence_document_id: str | None = None,
    source_locator: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    cur.execute(
        """
        insert into strategyos_claim_backfill_exceptions
            (tenant_id, run_id, ingestion_batch_id, evidence_document_id,
             record_type, record_key, source_locator, reason_code, detail, metadata)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        on conflict (ingestion_batch_id, record_type, record_key, reason_code)
        do update set detail = excluded.detail, metadata = excluded.metadata
        """,
        (
            tenant_id,
            run_id,
            batch_id,
            evidence_document_id,
            record_type,
            record_key,
            source_locator,
            reason_code,
            detail,
            json_blob(metadata or {}),
        ),
    )


def persist_transaction_claims(
    cur: Any,
    *,
    tenant_id: str,
    batch_id: str,
    run_id: str,
) -> dict[str, int]:
    """Materialize amount-bearing finance rows as governed actual claims.

    The existing transaction table remains the high-volume operational store.
    One claim per transaction gives retrieval and lineage a stable semantic
    handle without turning every spreadsheet cell into an independent claim.
    """
    cur.execute(
        """
        select transaction_type, natural_key, counterparty_key, event_date,
               amount_sar, currency, source_document_id, source_locator, attributes
        from strategyos_finance_transactions
        where tenant_id = %s and batch_id = %s
        order by transaction_type, natural_key
        """,
        (tenant_id, batch_id),
    )
    rows = fetchall_dicts(cur)
    claims = 0
    exceptions = 0
    for row in rows:
        transaction_type = str(row.get("transaction_type") or "finance_transaction")
        natural_key = str(row.get("natural_key") or "")
        record_key = f"{transaction_type}:{natural_key}"
        amount = money_value(row.get("amount_sar"))
        source_document_id = row.get("source_document_id")
        source_locator = text_value(row.get("source_locator"))
        if amount is None:
            exceptions += 1
            _record_claim_backfill_exception(
                cur,
                tenant_id=tenant_id,
                run_id=run_id,
                batch_id=batch_id,
                record_type="finance_transaction",
                record_key=record_key,
                reason_code="amount_missing",
                detail="The transaction has no usable monetary amount; no numeric claim was created.",
                evidence_document_id=source_document_id,
                source_locator=source_locator,
            )
            continue
        source_currency = text_value(row.get("currency")) or "SAR"
        if len(source_currency) != 3 or not source_currency.isalpha():
            exceptions += 1
            _record_claim_backfill_exception(
                cur,
                tenant_id=tenant_id,
                run_id=run_id,
                batch_id=batch_id,
                record_type="finance_transaction",
                record_key=record_key,
                reason_code="currency_invalid",
                detail="The transaction currency is missing or invalid; the claim is quarantined.",
                evidence_document_id=source_document_id,
                source_locator=source_locator,
                metadata={"currency": source_currency},
            )
            continue
        attributes = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
        business_unit = text_value(
            attributes.get("Business_Unit")
            or attributes.get("BusinessUnit")
            or attributes.get("BU")
        )
        event_date = date_value(row.get("event_date"))
        _revision_id, created = persist_shadow_claim(
            cur,
            tenant_id=tenant_id,
            batch_id=batch_id,
            subject_type=transaction_type,
            subject_key=natural_key,
            metric_key="finance.transaction.amount",
            claim_kind=ClaimKind.ACTUAL,
            value_numeric=amount,
            # The persisted field is amount_sar.  Keep its claim unit SAR even
            # when the originating transaction currency was different.
            unit="SAR",
            currency="SAR",
            source_document_id=source_document_id,
            source_locator=source_locator,
            business_unit=business_unit,
            dimensions={
                "transaction_type": transaction_type,
                "counterparty_key": text_value(row.get("counterparty_key")),
                "source_currency": source_currency.upper(),
            },
            period_start=event_date,
            period_end=event_date,
            metadata={
                "legacy_projection": "strategyos_finance_transactions",
                "run_id": str(run_id),
                "record_key": record_key,
            },
        )
        claims += int(created)
    return {"claims": claims, "exceptions": exceptions}


def persist_balance_claims(
    cur: Any,
    *,
    tenant_id: str,
    batch_id: str,
    run_id: str,
) -> dict[str, int]:
    """Backfill governed claims from already-persisted finance balances."""
    cur.execute(
        """
        select balance_type, natural_key, account, amount_sar,
               source_document_id, source_locator, attributes
        from strategyos_finance_balances
        where tenant_id = %s and batch_id = %s and amount_sar is not null
        order by balance_type, natural_key
        """,
        (tenant_id, batch_id),
    )
    claims = 0
    exceptions = 0
    for row in fetchall_dicts(cur):
        balance_type = str(row.get("balance_type") or "")
        natural_key = str(row.get("natural_key") or "")
        amount = money_value(row.get("amount_sar"))
        if balance_type == "trial_balance":
            claim_kind = ClaimKind.ACTUAL
            subject_type = "finance_account"
            metric_key = "finance.trial_balance.net"
            author_identity = None
            dimensions = {"account": text_value(row.get("account")) or natural_key}
        elif balance_type == "cash_forecast":
            claim_kind = ClaimKind.FORECAST
            subject_type = "cash_forecast_line"
            metric_key = "finance.cash_forecast.balance"
            author_identity = "source-role:cfo"
            attributes = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
            dimensions = {"sheet_name": text_value(attributes.get("sheet_name")) or "forecast"}
        else:
            exceptions += 1
            _record_claim_backfill_exception(
                cur,
                tenant_id=tenant_id,
                run_id=run_id,
                batch_id=batch_id,
                record_type="finance_balance",
                record_key=f"{balance_type}:{natural_key}",
                reason_code="balance_type_unknown",
                detail="The balance type has no governed claim mapping and was quarantined.",
                evidence_document_id=row.get("source_document_id"),
                source_locator=text_value(row.get("source_locator")),
            )
            continue
        if amount is None:
            exceptions += 1
            continue
        _revision_id, created = persist_shadow_claim(
            cur,
            tenant_id=tenant_id,
            batch_id=batch_id,
            subject_type=subject_type,
            subject_key=natural_key,
            metric_key=metric_key,
            claim_kind=claim_kind,
            value_numeric=amount,
            unit="SAR",
            currency="SAR",
            source_document_id=row.get("source_document_id"),
            source_locator=text_value(row.get("source_locator")),
            author_identity=author_identity,
            dimensions=dimensions,
            metadata={"legacy_projection": "strategyos_finance_balances"},
        )
        claims += int(created)
    return {"claims": claims, "exceptions": exceptions}


_FINANCE_KPI_COMPONENTS: dict[str, tuple[str, ClaimKind, str]] = {
    "revenue_actual": ("ceo.revenue", ClaimKind.ACTUAL, "revenue"),
    "revenue_plan": ("ceo.revenue", ClaimKind.PLAN, "revenue"),
    "cogs_actual": ("ceo.cogs", ClaimKind.ACTUAL, "ebitda_margin"),
    "ebitda_actual": ("ceo.ebitda", ClaimKind.ACTUAL, "ebitda_margin"),
    "ebitda_plan": ("ceo.ebitda", ClaimKind.PLAN, "ebitda_margin"),
    "operating_cost_actual": ("ceo.operating_cost", ClaimKind.ACTUAL, "operating_cost"),
    "operating_cost_plan": ("ceo.operating_cost", ClaimKind.PLAN, "operating_cost"),
    "cash_balance": ("ceo.cash_balance", ClaimKind.ACTUAL, "cash_vs_floor"),
    "board_floor": ("ceo.cash_floor", ClaimKind.PLAN, "cash_vs_floor"),
}


def _finance_period(value: Any) -> tuple[date | None, date | None]:
    text = str(value or "").strip()
    iso_dates = [date.fromisoformat(item) for item in re.findall(r"\d{4}-\d{2}-\d{2}", text)]
    if len(iso_dates) >= 2:
        return iso_dates[0], iso_dates[1]
    if len(iso_dates) == 1:
        return iso_dates[0], iso_dates[0]
    year_match = re.search(r"\b(20\d{2})\b", text)
    year = int(year_match.group(1)) if year_match else None
    normalized = text.casefold().replace("-", " ")
    if year and "h1" in normalized:
        return date(year, 1, 1), date(year, 6, 30)
    if year and "h2" in normalized:
        return date(year, 7, 1), date(year, 12, 31)
    if year and ("fy" in normalized or normalized == str(year)):
        return date(year, 1, 1), date(year, 12, 31)
    return None, None


def _aware_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _kpi_source_document(
    evidence_ids: dict[str, str],
    evidence_payload: dict[str, Any],
) -> tuple[str | None, str | None]:
    for source_path in list(evidence_payload.get("files") or []):
        normalized = str(source_path).replace("\\", "/")
        if normalized in evidence_ids:
            return evidence_ids[normalized], normalized
        matches = [
            (path, document_id)
            for path, document_id in evidence_ids.items()
            if path.replace("\\", "/").endswith(normalized)
            or normalized.endswith(path.replace("\\", "/"))
        ]
        if len(matches) == 1:
            return matches[0][1], matches[0][0]
    return None, None


def persist_finance_kpi_claims(
    cur: Any,
    *,
    tenant_id: str,
    batch_id: str,
    run_id: str,
    evidence_ids: dict[str, str],
    finance_payload: dict[str, Any],
    recorded_at: Any,
) -> dict[str, int]:
    """Persist every supplied headline component with actual/plan semantics."""
    if not finance_payload.get("authoritative"):
        return {"claims": 0, "exceptions": 0}
    components = finance_payload.get("components")
    if not isinstance(components, dict):
        return {"claims": 0, "exceptions": 0}
    evidence = finance_payload.get("evidence") if isinstance(finance_payload.get("evidence"), dict) else {}
    period_start, period_end = _finance_period(finance_payload.get("reporting_period_key"))
    as_of_at = _aware_datetime(recorded_at)
    claims = 0
    exceptions = 0
    component_revisions: dict[str, str] = {}
    for component_key, (metric_key, claim_kind, evidence_key) in _FINANCE_KPI_COMPONENTS.items():
        value = components.get(component_key)
        if value in (None, ""):
            continue
        amount = money_value(value)
        evidence_payload = evidence.get(evidence_key) if isinstance(evidence.get(evidence_key), dict) else {}
        source_document_id, source_path = _kpi_source_document(evidence_ids, evidence_payload)
        if amount is None:
            exceptions += 1
            _record_claim_backfill_exception(
                cur,
                tenant_id=tenant_id,
                run_id=run_id,
                batch_id=batch_id,
                record_type="finance_kpi_component",
                record_key=component_key,
                reason_code="value_invalid",
                detail="The supplied KPI component is not a finite decimal and was not materialized.",
                evidence_document_id=source_document_id,
                metadata={"value": str(value)},
            )
            continue
        if source_document_id is None:
            exceptions += 1
            _record_claim_backfill_exception(
                cur,
                tenant_id=tenant_id,
                run_id=run_id,
                batch_id=batch_id,
                record_type="finance_kpi_component",
                record_key=component_key,
                reason_code="evidence_unresolved",
                detail="The KPI component was retained with incomplete traceability because its source file could not be matched.",
                metadata={"evidence_key": evidence_key},
            )
        revision_id, created = persist_shadow_claim(
            cur,
            tenant_id=tenant_id,
            batch_id=batch_id,
            subject_type="enterprise",
            subject_key="group",
            metric_key=metric_key,
            claim_kind=claim_kind,
            value_numeric=amount,
            unit="SAR",
            currency="SAR",
            source_document_id=source_document_id,
            source_locator=(f"{evidence_key} component: {component_key}" if source_path else None),
            period_start=period_start,
            period_end=period_end,
            as_of_at=as_of_at,
            dimensions={"component_key": component_key},
            metadata={
                "legacy_projection": "run_summary.finance_kpi.components",
                "run_id": str(run_id),
                "component_key": component_key,
                "reporting_period_key": finance_payload.get("reporting_period_key"),
                "source_path": source_path,
            },
        )
        component_revisions[component_key] = revision_id
        claims += int(created)

    ebitda_revision = component_revisions.get("ebitda_actual")
    revenue_revision = component_revisions.get("revenue_actual")
    ebitda = money_value(components.get("ebitda_actual"))
    revenue = money_value(components.get("revenue_actual"))
    if ebitda_revision and revenue_revision and ebitda is not None and revenue not in (None, 0):
        margin = (ebitda / revenue) * 100
        _revision_id, created = persist_shadow_claim(
            cur,
            tenant_id=tenant_id,
            batch_id=batch_id,
            subject_type="enterprise",
            subject_key="group",
            metric_key="ceo.ebitda_margin",
            claim_kind=ClaimKind.ACTUAL,
            value_numeric=margin,
            unit="percent",
            currency=None,
            source_document_id=None,
            source_locator=None,
            period_start=period_start,
            period_end=period_end,
            as_of_at=as_of_at,
            production_method=ProductionMethod.CALCULATED,
            formula_key="ebitda-divided-by-revenue",
            formula_version="1",
            input_revision_ids=(ebitda_revision, revenue_revision),
            dimensions={"component_key": "ebitda_margin_actual"},
            metadata={
                "legacy_projection": "run_summary.finance_kpi.derived",
                "run_id": str(run_id),
                "component_key": "ebitda_margin_actual",
            },
        )
        claims += int(created)
    plan_ebitda_revision = component_revisions.get("ebitda_plan")
    plan_revenue_revision = component_revisions.get("revenue_plan")
    plan_ebitda = money_value(components.get("ebitda_plan"))
    plan_revenue = money_value(components.get("revenue_plan"))
    if (
        plan_ebitda_revision
        and plan_revenue_revision
        and plan_ebitda is not None
        and plan_revenue not in (None, 0)
    ):
        plan_margin = (plan_ebitda / plan_revenue) * 100
        _revision_id, created = persist_shadow_claim(
            cur,
            tenant_id=tenant_id,
            batch_id=batch_id,
            subject_type="enterprise",
            subject_key="group",
            metric_key="ceo.ebitda_margin",
            claim_kind=ClaimKind.PLAN,
            value_numeric=plan_margin,
            unit="percent",
            currency=None,
            source_document_id=None,
            source_locator=None,
            period_start=period_start,
            period_end=period_end,
            as_of_at=as_of_at,
            production_method=ProductionMethod.CALCULATED,
            formula_key="ebitda-divided-by-revenue",
            formula_version="1",
            input_revision_ids=(plan_ebitda_revision, plan_revenue_revision),
            dimensions={"component_key": "ebitda_margin_plan"},
            metadata={
                "legacy_projection": "run_summary.finance_kpi.derived",
                "run_id": str(run_id),
                "component_key": "ebitda_margin_plan",
            },
        )
        claims += int(created)
    return {"claims": claims, "exceptions": exceptions}


def persist_run_claim_snapshot(
    cur: Any,
    *,
    tenant_id: str,
    batch_id: str,
    run_id: str,
    as_of_at: Any,
) -> int:
    snapshot_key = f"run:{run_id}"
    cur.execute(
        """
        insert into strategyos_analysis_snapshots
            (tenant_id, snapshot_key, as_of_at, policy_version, created_by, metadata)
        values (%s, %s, %s, 'source-claim-v1', 'system:run-persistence', %s::jsonb)
        on conflict (tenant_id, snapshot_key) do nothing
        returning id
        """,
        (
            tenant_id,
            snapshot_key,
            datetime.now(UTC),
            json_blob(
                {
                    "run_id": str(run_id),
                    "batch_id": str(batch_id),
                    "data_as_of": (
                        _aware_datetime(as_of_at).isoformat()
                        if _aware_datetime(as_of_at)
                        else None
                    ),
                }
            ),
        ),
    )
    row = cur.fetchone()
    created = row is not None
    if row is None:
        # Replaying ingestion must not append new families to an already
        # published analysis. New evidence requires a new run/snapshot.
        return 0
    snapshot_id = row[0]
    cur.execute(
        """
        with batch_claims as (
            select distinct cr.id, cr.claim_family_id, cr.revision_number
            from strategyos_claim_revisions cr
            left join strategyos_claim_evidence_links cel on cel.claim_revision_id = cr.id
            left join strategyos_evidence_occurrences eo on eo.id = cel.evidence_occurrence_id
            left join strategyos_ingestion_batch_documents ibd
              on ibd.evidence_document_id = eo.evidence_document_id and ibd.batch_id = %s
            where cr.tenant_id = %s
              and (ibd.batch_id is not null or cr.metadata->>'batch_id' = %s)
        )
        select distinct on (claim_family_id) claim_family_id, id
        from batch_claims
        order by claim_family_id, revision_number desc
        """,
        (batch_id, tenant_id, str(batch_id)),
    )
    for claim_family_id, claim_revision_id in cur.fetchall():
        cur.execute(
            """
            insert into strategyos_analysis_snapshot_claims
                (snapshot_id, claim_family_id, claim_revision_id, selection_reason)
            values (%s, %s, %s, 'latest immutable revision materialized by this run')
            on conflict (snapshot_id, claim_family_id) do nothing
            """,
            (snapshot_id, claim_family_id, claim_revision_id),
        )
    return int(created)


def persist_claim_reconciliation(
    cur: Any,
    *,
    tenant_id: str,
    batch_id: str,
    run_id: str,
) -> int:
    cur.execute(
        """
        select
            (select count(*) from strategyos_finance_transactions
             where tenant_id = %s and batch_id = %s and amount_sar is not null)
          + (select count(*) from strategyos_finance_balances
             where tenant_id = %s and batch_id = %s and amount_sar is not null),
            (select coalesce(sum(amount_sar), 0) from strategyos_finance_transactions
             where tenant_id = %s and batch_id = %s and amount_sar is not null)
          + (select coalesce(sum(amount_sar), 0) from strategyos_finance_balances
             where tenant_id = %s and batch_id = %s and amount_sar is not null)
        """,
        (tenant_id, batch_id, tenant_id, batch_id, tenant_id, batch_id, tenant_id, batch_id),
    )
    source_record_count, source_amount = cur.fetchone()
    cur.execute(
        """
        select count(*), coalesce(sum(value_numeric), 0)
        from (
            select distinct cr.id, cr.value_numeric
            from strategyos_claim_revisions cr
            join strategyos_claim_evidence_links cel on cel.claim_revision_id = cr.id
            join strategyos_evidence_occurrences eo on eo.id = cel.evidence_occurrence_id
            join strategyos_ingestion_batch_documents ibd
              on ibd.evidence_document_id = eo.evidence_document_id and ibd.batch_id = %s
            where cr.tenant_id = %s
              and cr.metadata->>'legacy_projection' in
                  ('strategyos_finance_transactions', 'strategyos_finance_balances')
        ) linked_claims
        """,
        (batch_id, tenant_id),
    )
    claim_record_count, claim_amount = cur.fetchone()
    cur.execute(
        "select count(*) from strategyos_claim_backfill_exceptions where ingestion_batch_id = %s",
        (batch_id,),
    )
    exception_count = int(cur.fetchone()[0])
    difference = Decimal(str(claim_amount)) - Decimal(str(source_amount))
    counts_match = int(source_record_count) == int(claim_record_count)
    amounts_match = difference == Decimal("0")
    status = "passed" if counts_match and amounts_match and exception_count == 0 else "partial" if claim_record_count else "failed"
    checks = {
        "record_counts_match": counts_match,
        "amounts_match": amounts_match,
        "all_claims_have_source_or_lineage": exception_count == 0,
    }
    cur.execute(
        """
        insert into strategyos_claim_reconciliations
            (tenant_id, run_id, ingestion_batch_id, status, source_record_count,
             claim_record_count, exception_count, source_amount_sar, claim_amount_sar,
             difference_sar, checks)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        on conflict (run_id, ingestion_batch_id) do update set
            status = excluded.status,
            source_record_count = excluded.source_record_count,
            claim_record_count = excluded.claim_record_count,
            exception_count = excluded.exception_count,
            source_amount_sar = excluded.source_amount_sar,
            claim_amount_sar = excluded.claim_amount_sar,
            difference_sar = excluded.difference_sar,
            checks = excluded.checks,
            created_at = now()
        returning id
        """,
        (
            tenant_id,
            run_id,
            batch_id,
            status,
            int(source_record_count),
            int(claim_record_count),
            exception_count,
            source_amount,
            claim_amount,
            difference,
            json_blob(checks),
        ),
    )
    cur.fetchone()
    return 1


def persist_findings(cur: Any, run_id: str, findings: list[Finding]) -> int:
    for finding in findings:
        cur.execute(
            """
            insert into strategyos_findings
                (run_id, finding_id, pattern_type, vendor_id, vendor_name, status, confidence,
                 leakage_sar, recoverable_sar, finding_json)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            on conflict (run_id, finding_id) do update set
                status = excluded.status,
                confidence = excluded.confidence,
                finding_json = excluded.finding_json
            """,
            (
                run_id,
                finding.finding_id,
                finding.pattern_type,
                finding.vendor_id,
                finding.vendor_name,
                finding.status,
                finding.confidence,
                finding.leakage_sar,
                finding.recoverable_sar,
                json_blob(asdict(finding)),
            ),
        )
    return len(findings)


def persist_citations(
    cur: Any,
    run_id: str,
    evidence_ids: dict[str, str],
    bundle: DataBundle,
    findings: list[Finding],
) -> int:
    count = 0
    for finding in findings:
        for citation in finding.citations:
            resolved = resolve_citation(bundle, citation)
            cur.execute(
                """
                insert into strategyos_finding_citations
                    (run_id, finding_id, evidence_document_id, source_path, source_hash, locator, excerpt,
                     resolved, hash_match, resolved_payload)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    run_id,
                    finding.finding_id,
                    evidence_ids.get(citation.source_path),
                    citation.source_path,
                    citation.source_hash,
                    citation.locator,
                    citation.excerpt,
                    resolved["resolved"],
                    resolved["hash_match"],
                    json_blob(resolved.get("resolved_payload") or {}),
                ),
            )
            count += 1
    return count


def persist_audit_events(cur: Any, run_id: str, audit_events: list[AuditEvent]) -> int:
    for event in audit_events:
        cur.execute(
            """
            insert into strategyos_agent_events
                (run_id, round_no, actor, finding_id, action, detail, event_json)
            values (%s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                run_id,
                event.round_no,
                event.actor,
                event.finding_id,
                event.action,
                event.detail,
                json_blob(asdict(event)),
            ),
        )
    return len(audit_events)


def record_executive_directive(
    run_id: str,
    *,
    finding_id: str,
    action: str,
    actor: str,
    detail: str,
    subject: str = "",
) -> dict[str, Any]:
    """Log an executive's directive on a finding to the run's audit trail.

    A CEO does not approve recovery -- that gate belongs to the reviewer -- but
    a CEO can direct that a finding be recovered, and that directive is itself
    an accountable event: who asked, for what, when. It lands in the same
    strategyos_agent_events trail the execution log renders, so the request is
    visible to the reviewer and to the audit record rather than lost in a UI
    toast. The finding's status is not written here; the governed review flow
    still owns that transition.
    """
    from .access_scope import guard_run
    guard_run(run_id)
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped
    assert connection is not None
    normalized_run_id = str(run_id or "").strip()
    if not normalized_run_id:
        return {"status": "failed", "reason": "A run id is required to record a directive."}
    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into strategyos_agent_events
                    (run_id, round_no, actor, finding_id, action, detail, event_json)
                values (%s, %s, %s, %s, %s, %s, %s::jsonb)
                returning id, created_at
                """,
                (
                    normalized_run_id,
                    0,
                    actor,
                    str(finding_id or ""),
                    action,
                    detail,
                    json_blob(
                        {
                            "kind": "executive_directive",
                            "finding_id": str(finding_id or ""),
                            "action": action,
                            "actor": actor,
                            "subject": str(subject or ""),
                            "detail": detail,
                        }
                    ),
                ),
            )
            record = fetchone_dict(cur)
        conn.commit()
    return {"status": "recorded", "event": normalize_record(record) if record else None}


def record_executive_decision(
    run_id: str,
    *,
    decision_key: str,
    actor: str,
    subject: str,
    effect_key: str,
    recommendation_snapshot: dict[str, Any],
    selected_owner: dict[str, Any],
    due_date: dict[str, Any],
) -> dict[str, Any]:
    """Record a CEO decision without executing or delivering it.

    Human confirmation is enforced by the authenticated API route.  This store
    accepts no `requires_confirmation` or `send` flag: outbound delivery is not
    expressible in this Stage 1 operation.  An advisory lock makes retries with
    the same effect key idempotent even though the legacy audit table predates a
    dedicated effect-key column.
    """
    from .access_scope import guard_run
    guard_run(run_id)

    connection, skipped = database_connection()
    if skipped is not None:
        return skipped
    normalized_run_id = str(run_id or "").strip()
    normalized_decision_key = str(decision_key or "").strip()
    normalized_effect_key = str(effect_key or "").strip()
    if not normalized_run_id or not normalized_decision_key or not normalized_effect_key:
        return {
            "status": "failed",
            "reason": "Run id, decision key and effect key are required to record a decision.",
        }
    assert connection is not None
    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute("select pg_advisory_xact_lock(hashtext(%s))", (normalized_effect_key,))
            cur.execute(
                """
                select id, created_at, event_json
                from strategyos_agent_events
                where run_id = %s
                  and action = 'record_executive_decision'
                  and event_json ->> 'effect_key' = %s
                order by created_at desc
                limit 1
                """,
                (normalized_run_id, normalized_effect_key),
            )
            existing = fetchone_dict(cur)
            if existing is not None:
                conn.commit()
                return {
                    "status": "recorded",
                    "idempotent_replay": True,
                    "event": normalize_record(existing),
                }

            event_payload = {
                "kind": "executive_decision_recorded",
                "decision_key": normalized_decision_key,
                "effect_key": normalized_effect_key,
                "actor": actor,
                "subject": str(subject or ""),
                "decision_status": "recorded",
                "delivery_status": "not_delivered",
                "underlying_issue_status": "open",
                "recommendation_snapshot": recommendation_snapshot,
                "selected_owner": selected_owner,
                "due_date": due_date,
            }
            owner_label = " · ".join(
                item
                for item in (
                    str(selected_owner.get("name") or "").strip(),
                    str(selected_owner.get("role") or "").strip(),
                )
                if item
            ) or "accountable role"
            detail = (
                f"Executive recorded the {normalized_decision_key} decision for {owner_label}. "
                "No message was sent; the underlying issue remains open."
            )
            cur.execute(
                """
                insert into strategyos_agent_events
                    (run_id, round_no, actor, finding_id, action, detail, event_json)
                values (%s, 0, %s, null, 'record_executive_decision', %s, %s::jsonb)
                returning id, created_at, event_json
                """,
                (
                    normalized_run_id,
                    actor,
                    detail,
                    json_blob(event_payload),
                ),
            )
            record = fetchone_dict(cur)
        conn.commit()
    return {
        "status": "recorded",
        "idempotent_replay": False,
        "event": normalize_record(record) if record else None,
    }


def executive_decisions_for_run(run_id: str) -> dict[str, Any]:
    """Return recorded Stage 1 decisions; never imply delivery or closure."""
    from .access_scope import guard_run
    guard_run(run_id)

    connection, skipped = database_connection()
    if skipped is not None:
        return skipped
    normalized_run_id = str(run_id or "").strip()
    if not normalized_run_id:
        return {"status": "failed", "reason": "A run id is required."}
    assert connection is not None
    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, created_at, event_json
                from strategyos_agent_events
                where run_id = %s and action = 'record_executive_decision'
                order by created_at desc
                """,
                (normalized_run_id,),
            )
            rows = fetchall_dicts(cur)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        normalized = normalize_record(row)
        payload = normalized.get("event_json") if isinstance(normalized.get("event_json"), dict) else {}
        decision_key = str(payload.get("decision_key") or "")
        if not decision_key or decision_key in seen:
            continue
        seen.add(decision_key)
        records.append(
            {
                **payload,
                "event_id": normalized.get("id"),
                "recorded_at": normalized.get("created_at"),
            }
        )
    return {"status": "ok", "run_id": normalized_run_id, "records": records}


def persist_artifacts(
    cur: Any, run_id: str, artifacts: dict[str, Path], summary: dict[str, Any]
) -> int:
    upload_map = {
        item.get("artifact"): item.get("uri")
        for item in summary.get("object_store_uploads", [])
    }
    count = 0
    for artifact_name, local_path in artifacts.items():
        path = Path(local_path)
        cur.execute(
            """
            insert into strategyos_artifacts (run_id, artifact_name, local_path, object_uri, sha256)
            values (%s, %s, %s, %s, %s)
            """,
            (
                run_id,
                artifact_name,
                str(path),
                upload_map.get(path.name),
                sha256_file(path) if path.exists() and path.is_file() else None,
            ),
        )
        count += 1
    return count


def persist_knowledge_graph(
    cur: Any, tenant_id: str, run_id: str, knowledge_graph_path: Path | None
) -> dict[str, int]:
    if not knowledge_graph_path or not knowledge_graph_path.exists():
        return {"kg_nodes": 0, "kg_edges": 0}
    graph = json.loads(knowledge_graph_path.read_text(encoding="utf-8"))
    node_count = 0
    for node in graph.get("nodes", []):
        cur.execute(
            """
            insert into strategyos_kg_nodes (tenant_id, run_id, node_key, label, properties)
            values (%s, %s, %s, %s, %s::jsonb)
            on conflict (run_id, node_key) do update set properties = excluded.properties
            """,
            (
                tenant_id,
                run_id,
                node["id"],
                node.get("label", "Unknown"),
                json_blob(node.get("properties", {})),
            ),
        )
        node_count += 1
    edge_count = 0
    for edge in graph.get("edges", []):
        cur.execute(
            """
            insert into strategyos_kg_edges (tenant_id, run_id, source_node_key, target_node_key, label, properties)
            values (%s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                tenant_id,
                run_id,
                edge.get("source"),
                edge.get("target"),
                edge.get("label", "RELATED_TO"),
                json_blob(edge.get("properties", {})),
            ),
        )
        edge_count += 1
    return {"kg_nodes": node_count, "kg_edges": edge_count}


def count_for(cur: Any, table: str, column: str, value: Any) -> int:
    cur.execute(f"select count(*) from {table} where {column} = %s", (value,))
    return int(cur.fetchone()[0])


def count_profile_versions_for_tenant(cur: Any, tenant_id: str) -> int:
    cur.execute(
        """
        select count(*)
        from strategyos_tenant_profile_versions pv
        join strategyos_tenant_profiles p on p.id = pv.tenant_profile_id
        where p.tenant_id = %s
        """,
        (tenant_id,),
    )
    return int(cur.fetchone()[0])


def artifact_paths_for_run(cur: Any, run_id: str) -> dict[str, str]:
    from .access_scope import guard_run
    guard_run(run_id)
    cur.execute(
        """
        select artifact_name, local_path
        from strategyos_artifacts
        where run_id = %s
        """,
        (run_id,),
    )
    return {
        str(artifact_name): str(local_path)
        for artifact_name, local_path in cur.fetchall()
        if artifact_name and local_path
    }


def search_citations_for_run(run_id: str) -> list[dict[str, Any]]:
    from .access_scope import guard_run
    guard_run(run_id)
    connection, skipped = database_connection()
    if skipped is not None:
        return []

    assert connection is not None
    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    c.id::text as citation_id,
                    c.run_id::text as run_id,
                    c.finding_id,
                    c.evidence_document_id::text as evidence_document_id,
                    c.source_path,
                    c.source_hash,
                    c.locator,
                    c.excerpt,
                    c.resolved,
                    c.hash_match,
                    c.resolved_payload,
                    c.created_at,
                    f.pattern_type,
                    f.vendor_id,
                    f.vendor_name,
                    f.confidence,
                    f.recoverable_sar,
                    coalesce(f.finding_json->>'title', c.finding_id) as title
                from strategyos_finding_citations c
                left join strategyos_findings f
                    on f.run_id = c.run_id
                    and f.finding_id = c.finding_id
                where c.run_id = %s
                order by c.finding_id, c.created_at, c.id
                """,
                (run_id,),
            )
            return [
                normalize_search_citation_record(record)
                for record in fetchall_dicts(cur)
            ]


def evidence_preview_for_run(
    run_id: str,
    *,
    citation_id: str | None = None,
    finding_id: str | None = None,
    source_hash: str | None = None,
    locator: str | None = None,
) -> dict[str, Any]:
    from .access_scope import guard_run
    guard_run(run_id)
    if not any([citation_id, finding_id, source_hash, locator]):
        return {
            "status": "missing",
            "run_id": run_id,
            "reason": "At least one evidence selector is required.",
        }
    connection, skipped = database_connection()
    if skipped is not None:
        return {
            "status": "skipped",
            "run_id": run_id,
            "reason": skipped.get("reason", "DATABASE_URL is not configured."),
        }

    where = ["c.run_id = %s"]
    params: list[Any] = [run_id]
    if citation_id:
        where.append("c.id = %s")
        params.append(citation_id)
    if finding_id:
        where.append("c.finding_id = %s")
        params.append(finding_id)
    if source_hash:
        where.append("c.source_hash = %s")
        params.append(source_hash)
    if locator:
        where.append("c.locator = %s")
        params.append(locator)

    assert connection is not None
    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select
                    c.id::text as citation_id,
                    c.run_id::text as run_id,
                    c.finding_id,
                    c.evidence_document_id::text as evidence_document_id,
                    c.source_path,
                    c.source_hash,
                    c.locator,
                    c.excerpt,
                    c.resolved,
                    c.hash_match,
                    c.resolved_payload,
                    c.created_at,
                    f.pattern_type,
                    f.vendor_id,
                    f.vendor_name,
                    f.confidence,
                    f.recoverable_sar,
                    coalesce(f.finding_json->>'title', c.finding_id) as title
                from strategyos_finding_citations c
                left join strategyos_findings f
                    on f.run_id = c.run_id
                    and f.finding_id = c.finding_id
                where {" and ".join(where)}
                order by c.created_at, c.id
                limit 1
                """,
                tuple(params),
            )
            record = fetchone_dict(cur)
    if record is None:
        return {
            "status": "missing",
            "run_id": run_id,
            "reason": "No stored evidence matched the requested selector.",
        }
    citation = normalize_search_citation_record(record)
    excerpt = text_value(citation.get("excerpt")) or ""
    resolved_payload = citation.get("resolved_payload") or {}
    preview_kind = "text" if excerpt else "json" if resolved_payload else "metadata"
    return {
        "status": "ok",
        "run_id": run_id,
        "finding_id": citation.get("finding_id"),
        "citation_id": citation.get("citation_id"),
        "evidence_document_id": citation.get("evidence_document_id"),
        "title": citation.get("title"),
        "pattern_type": citation.get("pattern_type"),
        "vendor_id": citation.get("vendor_id"),
        "vendor_name": citation.get("vendor_name"),
        "confidence": citation.get("confidence"),
        "source_path": citation.get("source_path"),
        "source_hash": citation.get("source_hash"),
        "locator": citation.get("locator"),
        "resolved": citation.get("resolved"),
        "hash_match": citation.get("hash_match"),
        "preview_kind": preview_kind,
        "excerpt": preview_text(excerpt),
        "resolved_payload": bounded_json_value(resolved_payload),
    }


def normalize_search_citation_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_record(record)
    payload = normalized.get("resolved_payload")
    if isinstance(payload, str):
        try:
            normalized["resolved_payload"] = json.loads(payload)
        except json.JSONDecodeError:
            normalized["resolved_payload"] = {"raw": preview_text(payload)}
    elif payload is None:
        normalized["resolved_payload"] = {}
    normalized["recoverable_sar"] = money_value(normalized.get("recoverable_sar"))
    return normalized


def preview_text(value: str | None, limit: int = 4_000) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 15)].rstrip()}... truncated"


def bounded_json_value(value: Any, limit: int = 12_000) -> Any:
    try:
        encoded = json.dumps(value, default=json_value, sort_keys=True)
    except TypeError:
        return preview_text(str(value), limit)
    if len(encoded) <= limit:
        return value
    return {"preview": preview_text(encoded, limit), "truncated": True}


def row_to_dict(row: Any) -> dict[str, Any]:
    return {str(key): json_value(value) for key, value in row.to_dict().items()}


def json_value(value: Any) -> Any:
    try:
        import pandas as pd

        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def json_blob(value: Any) -> str:
    return json.dumps(value, default=json_value)


_PG_POOL: Any | None = None
_PG_POOL_LOCK = threading.Lock()
_PG_POOL_DATABASE_URL: str | None = None


def _get_pool() -> Any | None:
    """Return the process-wide Postgres connection pool, creating it on
    first use. Memoized on CONFIG.database_url so a config reload (e.g. in
    tests that monkeypatch CONFIG) opens a fresh pool instead of reusing a
    stale one pointed at a different database."""
    global _PG_POOL, _PG_POOL_DATABASE_URL
    if not CONFIG.database_url:
        return None
    if _PG_POOL is not None and _PG_POOL_DATABASE_URL == CONFIG.database_url:
        return _PG_POOL
    with _PG_POOL_LOCK:
        if _PG_POOL is not None and _PG_POOL_DATABASE_URL == CONFIG.database_url:
            return _PG_POOL
        from psycopg_pool import ConnectionPool

        if _PG_POOL is not None:
            _PG_POOL.close()
        _PG_POOL = ConnectionPool(
            CONFIG.database_url,
            min_size=CONFIG.pg_pool_min_size,
            max_size=CONFIG.pg_pool_max_size,
            open=True,
            timeout=CONFIG.pg_pool_timeout_seconds,
            name="strategyos",
        )
        _PG_POOL_DATABASE_URL = CONFIG.database_url
        atexit.register(_PG_POOL.close)
    return _PG_POOL


class _PooledConnectionHandle:
    """Wraps a connection checked out from the pool via ``pool.getconn()``.

    psycopg3's ``Connection.__exit__`` only skips ``close()`` for a
    pool-owned connection (``conn._pool`` is set once, permanently, at
    connection-creation time inside psycopg_pool) -- it never calls
    ``pool.putconn()``. Relying on ``with conn:`` alone therefore leaves
    every checked-out connection permanently outstanding and depletes the
    pool after ``max_size`` calls (verified empirically: a bare
    ``pool.getconn()`` + ``with conn:`` loop raises ``PoolTimeout`` on the
    (max_size + 1)-th iteration). This handle calls ``putconn()`` on exit
    so the connection is genuinely returned, while preserving the exact
    ``connection, skipped = database_connection()`` / ``with connection as
    conn:`` contract every call site already uses -- no call-site changes.
    """

    __slots__ = ("_pool", "_conn")

    def __init__(self, pool: Any, conn: Any) -> None:
        self._pool = pool
        self._conn = conn

    def __enter__(self) -> Any:
        self._conn.__enter__()
        return self._conn

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        try:
            self._conn.__exit__(exc_type, exc_val, exc_tb)
        finally:
            self._pool.putconn(self._conn)
        return False


def database_connection() -> tuple[Any | None, dict[str, Any] | None]:
    if not CONFIG.database_url:
        return None, {"status": "skipped", "reason": "DATABASE_URL is not configured."}
    try:
        import psycopg  # noqa: F401  (preserves the "psycopg not installed" skip path)
        import psycopg_pool  # noqa: F401
    except Exception as exc:  # pragma: no cover - optional cloud dependency
        return None, {"status": "skipped", "reason": f"psycopg/psycopg_pool is not installed: {exc}"}
    try:
        pool = _get_pool()
        assert pool is not None
        conn = pool.getconn()
        return _PooledConnectionHandle(pool, conn), None
    except Exception:
        return None, {
            "status": "failed",
            "reason": "Database backing status is temporarily unavailable.",
        }


def fetchone_dict(cur: Any) -> dict[str, Any] | None:
    row = cur.fetchone()
    if row is None:
        return None
    return row_to_mapping(cur, row)


def fetchall_dicts(cur: Any) -> list[dict[str, Any]]:
    rows = cur.fetchall()
    return [row_to_mapping(cur, row) for row in rows]


def row_to_mapping(cur: Any, row: Any) -> dict[str, Any]:
    columns = []
    for description in cur.description or []:
        columns.append(getattr(description, "name", description[0]))
    return {column: value for column, value in zip(columns, row, strict=False)}


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in record.items():
        if key.endswith("_json") or key == "payload":
            if isinstance(value, str):
                try:
                    normalized[key] = json.loads(value)
                    continue
                except json.JSONDecodeError:
                    pass
        if isinstance(value, (datetime, date)):
            normalized[key] = value.isoformat()
        elif value is None:
            normalized[key] = None
        else:
            normalized[key] = (
                str(value)
                if key in {"id", "run_id", "checkpoint_id", "approval_id"}
                else value
            )
    return normalized


def normalize_run_job_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_record(record)
    normalized["job_id"] = normalized.pop("id")
    if normalized.get("strategyos_run_id") is not None:
        normalized["strategyos_run_id"] = str(normalized["strategyos_run_id"])
    return normalized


def run_status_for_decision(decision: str) -> str:
    return {
        "approved": "approved",
        "rejected": "rejected",
        "needs_more_evidence": "awaiting_review",
        "edited": "awaiting_review",
    }.get(decision, "awaiting_review")


def text_value(value: Any) -> str | None:
    normalized = json_value(value)
    if normalized is None:
        return None
    text = str(normalized).strip()
    return text or None


def uuid_value(value: Any) -> str | None:
    text = text_value(value)
    if text is None:
        return None
    try:
        return str(UUID(text))
    except ValueError:
        return None


def date_value(value: Any) -> date | None:
    normalized = json_value(value)
    if normalized is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(normalized)).date()
    except ValueError:
        return None


def money_value(value: Any) -> float | None:
    normalized = json_value(value)
    if normalized is None:
        return None
    try:
        number = float(normalized)
        return round(number, 2) if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def gl_amount(row: Any) -> float | None:
    debit_value = money_value(row.get("Debit"))
    credit_value = money_value(row.get("Credit"))
    if debit_value is None and credit_value is None:
        return None
    debit = debit_value or 0.0
    credit = credit_value or 0.0
    amount = debit - credit
    return round(amount, 2)


def media_type_for(rel_path: str) -> str:
    suffix = Path(rel_path).suffix.lower()
    return {
        ".csv": "text/csv",
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }.get(suffix, "application/octet-stream")


def schema_path() -> Path:
    return Path(__file__).resolve().parents[1] / "deploy" / "postgres" / "schema.sql"
