from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from .citation_resolver import resolve_citation
from .config import CONFIG
from .evidence import row_locator, sha256_file
from .ingestion import DataBundle
from .models import AuditEvent, Finding


def create_run(
    summary_seed: dict[str, Any], *, requires_human_review: bool
) -> dict[str, Any]:
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
                     status, current_stage, requires_human_review, summary_json)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
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
        request_payload,
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
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    request_hash = run_job_request_hash(request_payload)
    assert connection is not None
    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
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
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

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


def list_pending_reviews() -> list[dict[str, Any]] | dict[str, Any]:
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
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
                order by coalesce(rc.created_at, r.created_at) desc
                """
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
            return items


def list_recent_runs(limit: int = 12) -> list[dict[str, Any]] | dict[str, Any]:
    connection, skipped = database_connection()
    if skipped is not None:
        return skipped

    assert connection is not None
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
                order by coalesce(rc.created_at, r.created_at) desc
                limit %s
                """,
                (max(1, min(int(limit), 50)),),
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
            return items


def claim_pending_review(
    run_id: str,
    reviewer_subject: str,
) -> dict[str, Any]:
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
    if not CONFIG.database_url:
        return {"status": "skipped", "reason": "DATABASE_URL is not configured."}
    try:
        import psycopg
    except Exception as exc:  # pragma: no cover - optional cloud dependency
        return {"status": "skipped", "reason": f"psycopg is not installed: {exc}"}

    findings = findings or []
    artifacts = artifacts or {}
    audit_events = audit_events or []

    with psycopg.connect(CONFIG.database_url) as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            tenant_id = upsert_tenant(cur)
            source_system_id = upsert_source_system(cur, tenant_id)
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
                        cur, tenant_id, batch_id, evidence_ids, bundle
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
    if not CONFIG.database_url:
        return {"status": "skipped", "reason": "DATABASE_URL is not configured."}
    try:
        import psycopg
    except Exception as exc:  # pragma: no cover - optional cloud dependency
        return {"status": "skipped", "reason": f"psycopg is not installed: {exc}"}

    try:
        with psycopg.connect(CONFIG.database_url) as conn:
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
                    run_id = str(row[0])
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
                    (run_id,),
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
    except Exception as exc:
        return {"status": "failed", "reason": str(exc)}


def ensure_data_schema(conn: Any) -> None:
    sql = schema_path().read_text(encoding="utf-8")
    with conn.cursor() as cur:
        for statement in sql.split(";"):
            statement = statement.strip()
            if statement:
                cur.execute(statement)
    conn.commit()


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


def upsert_source_system(cur: Any, tenant_id: str) -> str:
    cur.execute(
        """
        insert into strategyos_source_systems (tenant_id, name, system_type)
        values (%s, %s, %s)
        on conflict (tenant_id, name, system_type) do update set status = 'active'
        returning id
        """,
        (tenant_id, CONFIG.source_system_name, "finance_dataset"),
    )
    return cur.fetchone()[0]


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
             status, current_stage, requires_human_review, approved_at, approved_by, summary_json)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
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
) -> dict[str, int]:
    counts = {
        "finance_entities": 0,
        "finance_transactions": 0,
        "finance_balances": 0,
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
    counts["finance_balances"] += persist_trial_balance(
        cur,
        tenant_id,
        batch_id,
        evidence_ids.get("02_ERP_Extracts/Trial_Balance_June_2026.xlsx"),
        bundle,
    )
    counts["finance_balances"] += persist_cash_forecast(
        cur, tenant_id, batch_id, evidence_ids, bundle
    )
    return counts


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
) -> int:
    count = 0
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
        count += 1
    return count


def persist_cash_forecast(
    cur: Any,
    tenant_id: str,
    batch_id: str,
    evidence_ids: dict[str, str],
    bundle: DataBundle,
) -> int:
    count = 0
    source_document_id = evidence_ids.get(
        "07_Cash_Forecast/CFO_Cash_Forecast_June_2026.xlsx"
    )
    for sheet_name, df in bundle.cash_forecast.items():
        for idx, row in df.iterrows():
            payload = row_to_dict(row) | {"sheet_name": sheet_name}
            natural_key = f"{sheet_name}:{idx}"
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
                    money_value(row.get("Balance (SAR)"))
                    or money_value(row.get("H2_Total_LC")),
                    source_document_id,
                    f"{sheet_name} sheet row {idx + 2}",
                    json_blob(payload),
                ),
            )
            count += 1
    return count


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


def database_connection() -> tuple[Any | None, dict[str, Any] | None]:
    if not CONFIG.database_url:
        return None, {"status": "skipped", "reason": "DATABASE_URL is not configured."}
    try:
        import psycopg
    except Exception as exc:  # pragma: no cover - optional cloud dependency
        return None, {"status": "skipped", "reason": f"psycopg is not installed: {exc}"}
    try:
        return psycopg.connect(CONFIG.database_url), None
    except Exception as exc:
        return None, {"status": "failed", "reason": str(exc)}


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
        return round(float(normalized), 2)
    except (TypeError, ValueError):
        return None


def gl_amount(row: Any) -> float | None:
    debit = money_value(row.get("Debit")) or 0.0
    credit = money_value(row.get("Credit")) or 0.0
    amount = debit - credit
    return round(amount, 2) if amount else None


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
