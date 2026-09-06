from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import Any, Iterable

from .source_claims import SourceRegistration, stable_key
from .state_store import (
    database_connection,
    ensure_data_schema,
    fetchall_dicts,
    json_blob,
    persist_balance_claims,
    persist_claim_reconciliation,
    persist_finance_kpi_claims,
    persist_run_claim_snapshot,
    persist_source_access_policy,
    persist_source_registration_version,
    persist_transaction_claims,
)


LEGACY_READ_POLICY = {
    "allowed_roles": [
        "tenant_admin",
        "system",
        "operator",
        "reviewer",
        "analyst",
        "auditor",
        "executive",
        "bu",
    ],
    "allowed_purposes": [
        "operations",
        "executive_briefing",
        "analysis",
        "scenario",
        "export",
    ],
    "export_allowed": True,
    "external_model_allowed": False,
    "quote_allowed": False,
}


def _target_rows(cur: Any, run_ids: Iterable[str] | None) -> list[dict[str, Any]]:
    ids = [str(value) for value in (run_ids or []) if str(value).strip()]
    cur.execute(
        """
        select distinct on (r.id)
               r.id as run_id, r.summary_json, r.created_at as run_created_at,
               b.id as batch_id, b.tenant_id, b.source_system_id,
               s.name as source_name, s.system_type, s.source_key,
               s.origin_category, s.capture_method, s.governed_owner,
               s.provider_name, s.authorization_basis, s.license_policy_ref,
               s.metadata as source_metadata
        from strategyos_runs r
        join strategyos_ingestion_batches b on b.run_id = r.id
        join strategyos_source_systems s on s.id = b.source_system_id
        where (cardinality(%s::text[]) = 0 or r.id::text = any(%s::text[]))
        order by r.id, b.completed_at desc, b.id desc
        """,
        (ids, ids),
    )
    rows = fetchall_dicts(cur)
    if ids:
        found = {str(row["run_id"]) for row in rows}
        missing = sorted(set(ids) - found)
        if missing:
            raise KeyError("Runs with persisted ingestion batches were not found: " + ", ".join(missing))
    return rows


def _preview(cur: Any, row: dict[str, Any]) -> dict[str, Any]:
    cur.execute(
        """
        select
            (select count(*) from strategyos_ingestion_batch_documents where batch_id = %s),
            (select count(*) from strategyos_finance_transactions where batch_id = %s and amount_sar is not null),
            (select count(*) from strategyos_finance_balances where batch_id = %s and amount_sar is not null),
            (select count(*) from strategyos_claim_revisions where tenant_id = %s and metadata->>'batch_id' = %s),
            (select status from strategyos_claim_reconciliations where run_id = %s and ingestion_batch_id = %s)
        """,
        (
            row["batch_id"],
            row["batch_id"],
            row["batch_id"],
            row["tenant_id"],
            str(row["batch_id"]),
            row["run_id"],
            row["batch_id"],
        ),
    )
    documents, transactions, balances, claims, reconciliation = cur.fetchone()
    return {
        "run_id": str(row["run_id"]),
        "batch_id": str(row["batch_id"]),
        "tenant_id": str(row["tenant_id"]),
        "source_key": str(row["source_key"]),
        "documents": int(documents),
        "finance_transactions": int(transactions),
        "finance_balances": int(balances),
        "existing_claim_revisions": int(claims),
        "existing_reconciliation": reconciliation,
    }


def _ensure_source_contract(cur: Any, row: dict[str, Any]) -> None:
    source = SourceRegistration(
        tenant_id=str(row["tenant_id"]),
        source_key=str(row["source_key"]),
        display_name=str(row["source_name"]),
        origin_category=str(row.get("origin_category") or "unknown"),
        capture_method=str(row.get("capture_method") or "unknown"),
        governed_owner=row.get("governed_owner"),
        provider_name=row.get("provider_name"),
        authorization_basis=row.get("authorization_basis"),
        license_policy_ref=row.get("license_policy_ref"),
        metadata=dict(row.get("source_metadata") or {}),
    )
    persist_source_registration_version(
        cur,
        tenant_id=str(row["tenant_id"]),
        source_system_id=str(row["source_system_id"]),
        source=source,
        recorded_by="system:claim-backfill",
        rationale="Historical source registration captured before claim materialization.",
    )
    cur.execute(
        "select 1 from strategyos_source_access_policies where source_system_id = %s and effective_to is null",
        (row["source_system_id"],),
    )
    if cur.fetchone() is not None:
        return
    if str(row.get("system_type") or "") != "finance_dataset":
        raise RuntimeError(
            f"Source {row['source_key']} has no active access policy; backfill fails closed."
        )
    persist_source_access_policy(
        cur,
        tenant_id=str(row["tenant_id"]),
        source_system_id=str(row["source_system_id"]),
        source_key=str(row["source_key"]),
        policy_payload=LEGACY_READ_POLICY,
        recorded_by="system:claim-backfill",
        rationale=(
            "Historical finance-source parity policy. External-model and quotation use remain denied."
        ),
    )


def _ensure_occurrences(cur: Any, row: dict[str, Any]) -> dict[str, str]:
    cur.execute(
        """
        select d.id, d.source_path, d.source_hash, d.source_uri,
               d.first_seen_at, d.manifest_json
        from strategyos_ingestion_batch_documents bd
        join strategyos_evidence_documents d on d.id = bd.evidence_document_id
        where bd.batch_id = %s
        order by d.source_path
        """,
        (row["batch_id"],),
    )
    documents = fetchall_dicts(cur)
    evidence_ids: dict[str, str] = {}
    for document in documents:
        source_path = str(document["source_path"])
        digest = str(document["source_hash"])
        evidence_ids[source_path] = str(document["id"])
        occurrence_key = stable_key(
            "occurrence",
            row["tenant_id"],
            row["source_key"],
            source_path,
            digest,
        )
        manifest = document.get("manifest_json") if isinstance(document.get("manifest_json"), dict) else {}
        cur.execute(
            """
            insert into strategyos_evidence_occurrences
                (tenant_id, source_system_id, evidence_document_id, ingestion_batch_id,
                 occurrence_key, source_native_id, source_native_version,
                 original_uri, received_at, metadata)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            on conflict (tenant_id, occurrence_key) do nothing
            """,
            (
                row["tenant_id"],
                row["source_system_id"],
                document["id"],
                row["batch_id"],
                occurrence_key,
                source_path,
                digest,
                document.get("source_uri") or f"dataset://{source_path}",
                document.get("first_seen_at") or datetime.now(UTC),
                json_blob(
                    {
                        "source_disposition": manifest.get("source_disposition"),
                        "classification": manifest.get("classification"),
                        "historical_backfill": True,
                    }
                ),
            ),
        )
    return evidence_ids


def backfill_claims(
    *,
    run_ids: Iterable[str] | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    connection, skipped = database_connection()
    if connection is None:
        raise RuntimeError(str((skipped or {}).get("reason") or "Database is unavailable."))
    with connection as conn:
        ensure_data_schema(conn)
        with conn.cursor() as cur:
            targets = _target_rows(cur, run_ids)
            previews = [_preview(cur, row) for row in targets]
            if not apply:
                return {"mode": "preview", "runs": previews}
            results: list[dict[str, Any]] = []
            for row, preview in zip(targets, previews, strict=True):
                cur.execute(
                    "select pg_advisory_xact_lock(hashtext(%s))",
                    (f"strategyos-claim-backfill:{row['run_id']}",),
                )
                _ensure_source_contract(cur, row)
                evidence_ids = _ensure_occurrences(cur, row)
                summary = row.get("summary_json") if isinstance(row.get("summary_json"), dict) else {}
                finance_payload = summary.get("finance_kpi")
                if not isinstance(finance_payload, dict):
                    finance_payload = summary.get("oracle_kpi") if isinstance(summary.get("oracle_kpi"), dict) else {}
                transaction_result = persist_transaction_claims(
                    cur,
                    tenant_id=str(row["tenant_id"]),
                    batch_id=str(row["batch_id"]),
                    run_id=str(row["run_id"]),
                )
                balance_result = persist_balance_claims(
                    cur,
                    tenant_id=str(row["tenant_id"]),
                    batch_id=str(row["batch_id"]),
                    run_id=str(row["run_id"]),
                )
                kpi_result = persist_finance_kpi_claims(
                    cur,
                    tenant_id=str(row["tenant_id"]),
                    batch_id=str(row["batch_id"]),
                    run_id=str(row["run_id"]),
                    evidence_ids=evidence_ids,
                    finance_payload=finance_payload,
                    recorded_at=summary.get("created_at") or row.get("run_created_at"),
                )
                snapshot_created = persist_run_claim_snapshot(
                    cur,
                    tenant_id=str(row["tenant_id"]),
                    batch_id=str(row["batch_id"]),
                    run_id=str(row["run_id"]),
                    as_of_at=summary.get("created_at") or row.get("run_created_at"),
                )
                persist_claim_reconciliation(
                    cur,
                    tenant_id=str(row["tenant_id"]),
                    batch_id=str(row["batch_id"]),
                    run_id=str(row["run_id"]),
                )
                updated = _preview(cur, row)
                results.append(
                    {
                        **preview,
                        "created": {
                            "transaction_claims": transaction_result["claims"],
                            "balance_claims": balance_result["claims"],
                            "kpi_claims": kpi_result["claims"],
                            "exceptions": (
                                transaction_result["exceptions"]
                                + balance_result["exceptions"]
                                + kpi_result["exceptions"]
                            ),
                            "analysis_snapshot": snapshot_created,
                        },
                        "result": updated,
                    }
                )
            conn.commit()
    return {"mode": "apply", "runs": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preview or materialize governed claims for persisted StrategyOS runs."
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--run-id", action="append", dest="run_ids")
    target.add_argument("--all", action="store_true")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit the backfill. Without this flag the command is read-only.",
    )
    args = parser.parse_args(argv)
    result = backfill_claims(run_ids=None if args.all else args.run_ids, apply=args.apply)
    print(json.dumps(result, indent=2, default=str, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
