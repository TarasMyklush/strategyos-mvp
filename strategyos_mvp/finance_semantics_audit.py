"""Read-only re-evaluation of historical finance interpretations.

Never rewrite an approved snapshot. An operator must review this evidence before
withdrawing an old assertion or publishing a separately versioned analysis.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .source_finance_kpis import derive_source_finance_kpis
from .state_store import database_connection, fetchall_dicts


def audit_run(run_id: str) -> dict[str, Any]:
    connection, _ = database_connection()
    if connection is None:
        raise RuntimeError("Database unavailable; no audit was performed.")
    with connection as conn, conn.cursor() as cur:
        cur.execute("select dataset_root from strategyos_runs where id=%s", (run_id,))
        found = cur.fetchone()
        if found is None:
            raise KeyError("Run not found.")
        root = Path(found[0]).resolve(strict=True)
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
              and r.metadata->>'legacy_projection'='run_summary.finance_kpi.components'
            order by f.metric_key,r.revision_number""", (str(run_id),))
        candidates = []
        for record in fetchall_dicts(cur):
            key = (record.get("dimensions") or {}).get("component_key")
            if record["claim_kind"] == "actual" and key in ambiguous:
                candidates.append({"claim_revision_id": str(record["id"]),
                    "metric_key": record["metric_key"], "component_key": key,
                    "reason": ambiguous[key]["reason"], "recommended_action": "review_and_withdraw_actual_classification"})
    return {"mode": "read_only", "run_id": run_id,
        "source_semantics_version": fresh.get("source_semantics_version"),
        "checked_sources": checked, "review_required": candidates,
        "approved_snapshot_modified": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(json.dumps(audit_run(args.run_id), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
