"""Re-evaluate historical finance interpretations; read-only by default.

An explicit digest-bound operation may record failed machine validation. It
never reclassifies a value, approves a forecast or rewrites a frozen snapshot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .source_finance_kpis import derive_source_finance_kpis
from .state_store import database_connection, fetchall_dicts


def audit_run(run_id: str) -> dict[str, Any]:
    connection, _ = database_connection()
    if connection is None:
        raise RuntimeError("Database unavailable; no audit was performed.")
    with connection as conn, conn.cursor() as cur:
        cur.execute("select dataset_root,tenant_key from strategyos_runs where id=%s", (run_id,))
        found = cur.fetchone()
        if found is None:
            raise KeyError("Run not found.")
        root = Path(found[0]).resolve(strict=True)
        tenant_key = found[1]
        cur.execute("""select distinct d.source_path,d.source_hash from strategyos_evidence_documents d
            join strategyos_ingestion_batch_documents bd on bd.evidence_document_id=d.id
            join strategyos_ingestion_batches b on b.id=bd.batch_id where b.run_id=%s""", (run_id,))
        documents = fetchall_dicts(cur)
        hashes: dict[str, str] = {}
        for row in documents:
            path, digest = row["source_path"], row["source_hash"]
            if path in hashes and hashes[path] != digest:
                raise ValueError("Recorded source versions conflict; explicit resolution is required.")
            hashes[path] = digest
        fresh = derive_source_finance_kpis(root)
        checked = []
        for source in fresh.get("source_files", []):
            path = (root / source).resolve(strict=True)
            if not path.is_relative_to(root):
                raise ValueError("Source path escapes the recorded dataset.")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            recorded_path = source
            if source not in hashes:
                # Normalization can relocate an unchanged workbook. Accept only
                # one recorded suffix match with the exact original bytes, and
                # expose both paths rather than silently merging occurrences.
                candidates = [name for name, value in hashes.items()
                              if name.endswith("/" + source) and value == digest]
                if len(candidates) == 1:
                    recorded_path = candidates[0]
            if hashes.get(recorded_path) != digest:
                raise ValueError("Source bytes do not match the recorded run; re-import is required.")
            checked.append({"source_path": source, "recorded_source_path": recorded_path, "sha256": digest})
        if not checked:
            raise ValueError("No reproducible finance sources are available for this run.")
        ambiguous = fresh.get("ambiguous_components", {})
        cur.execute("""select r.id,r.claim_kind,f.metric_key,f.dimensions,
                       r.value_numeric,r.metadata
            from strategyos_claim_revisions r join strategyos_claim_families f on f.id=r.claim_family_id
            where r.metadata->>'run_id'=%s
              and r.tenant_id in (select id from strategyos_tenants where id::text=%s or slug=%s)
              and r.metadata->>'legacy_projection'='run_summary.finance_kpi.components'
            order by f.metric_key,r.revision_number""", (str(run_id), tenant_key, tenant_key))
        candidates = []
        for record in fetchall_dicts(cur):
            key = (record.get("dimensions") or {}).get("component_key")
            if record["claim_kind"] == "actual" and key in ambiguous:
                candidates.append({"claim_revision_id": str(record["id"]),
                    "metric_key": record["metric_key"], "component_key": key,
                    "reason": ambiguous[key]["reason"], "recommended_action": "review_and_withdraw_actual_classification"})
    report = {"mode": "read_only", "run_id": run_id,
        "source_semantics_version": fresh.get("source_semantics_version"),
        "checked_sources": checked, "review_required": candidates,
        "approved_snapshot_modified": False}
    report['audit_digest'] = hashlib.sha256(json.dumps(report,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return report


def record_invalidity(run_id: str, *, expected_audit_digest: str) -> dict[str, Any]:
    """Append negative rule findings only after rechecking the exact source bytes.

    No claim becomes an actual/forecast or gains approval through this operation.
    Corrections need new revisions. Retries preserve the original assessment time.
    """
    from .claim_store import ClaimRepository
    from .source_claims import ClaimAssessment
    report = audit_run(run_id)
    if not expected_audit_digest or report['audit_digest'] != expected_audit_digest:
        raise ValueError('Audit changed or was not reviewed; run the read-only audit again.')
    repo = ClaimRepository()
    receipts = []
    for item in report['review_required']:
        effect_key = 'finance-semantic-invalidity:' + hashlib.sha256(
            (report['audit_digest'] + ':' + item['claim_revision_id']).encode()).hexdigest()
        connection, _ = database_connection()
        if connection is None:
            raise RuntimeError('Database unavailable; validation recording can be retried.')
        with connection as conn, conn.cursor() as cur:
            cur.execute('SELECT assessed_at FROM strategyos_claim_assessments WHERE claim_revision_id=%s AND effect_key=%s',
                (item['claim_revision_id'],effect_key))
            previous = cur.fetchone()
        assessment = ClaimAssessment(claim_revision_id=item['claim_revision_id'],
            assessment_type='validation',result='failed',
            rule_version='finance-source-semantics:' + str(report['source_semantics_version']),
            assessed_by='system:finance-semantics-audit',
            assessed_at=previous[0] if previous else datetime.now(UTC),
            reasons=(item['reason'], 'Verified source audit: ' + report['audit_digest']))
        receipts.append(repo.assess_claim(assessment,effect_key=effect_key))
    return {**report,'mode':'record_invalidity','assessments':receipts,
        'source_values_reclassified':False,'analysis_published':False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument('--record-invalidity',action='store_true')
    parser.add_argument('--expected-audit-digest')
    args = parser.parse_args()
    result = record_invalidity(args.run_id,expected_audit_digest=args.expected_audit_digest) if args.record_invalidity else audit_run(args.run_id)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
