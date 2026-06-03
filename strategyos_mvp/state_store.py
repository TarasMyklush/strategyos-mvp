from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .citation_resolver import resolve_citation
from .config import CONFIG
from .evidence import row_locator, sha256_file
from .ingestion import DataBundle
from .models import AuditEvent, Finding


def persist_run_summary(
    summary: dict[str, Any],
    *,
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
            run_id = insert_run_summary(cur, summary)
            counts: dict[str, int] = {}
            if bundle is not None:
                batch_id = insert_ingestion_batch(cur, tenant_id, source_system_id, run_id, summary, bundle)
                evidence_ids = persist_evidence_documents(cur, tenant_id, source_system_id, batch_id, bundle, summary)
                counts.update(persist_finance_records(cur, tenant_id, batch_id, evidence_ids, bundle))
                counts["evidence_documents"] = len(evidence_ids)
                counts["findings"] = persist_findings(cur, run_id, findings)
                counts["citations"] = persist_citations(cur, run_id, evidence_ids, bundle, findings)
                counts["audit_events"] = persist_audit_events(cur, run_id, audit_events)
                counts.update(persist_knowledge_graph(cur, tenant_id, run_id, artifacts.get("knowledge_graph")))
            counts["artifacts"] = persist_artifacts(cur, run_id, artifacts, summary)
        conn.commit()
    return {"status": "persisted", "run_id": str(run_id), "data_management": counts}


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
                    cur.execute("select id from strategyos_runs order by created_at desc limit 1")
                    row = cur.fetchone()
                    if row is None:
                        return {"status": "missing", "reason": "No StrategyOS run has been persisted."}
                    run_id = str(row[0])
                cur.execute(
                    """
                    select ib.id, t.slug, ss.name, ib.dataset_root
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
                    return {"status": "missing", "run_id": run_id, "reason": "No data-management batch for this run."}
                batch_id, tenant_slug, source_system_name, dataset_root = batch
                counts = {
                    "evidence_documents": count_for(cur, "strategyos_ingestion_batch_documents", "batch_id", batch_id),
                    "finance_entities": count_for(cur, "strategyos_finance_entities", "batch_id", batch_id),
                    "finance_transactions": count_for(cur, "strategyos_finance_transactions", "batch_id", batch_id),
                    "finance_balances": count_for(cur, "strategyos_finance_balances", "batch_id", batch_id),
                    "findings": count_for(cur, "strategyos_findings", "run_id", run_id),
                    "citations": count_for(cur, "strategyos_finding_citations", "run_id", run_id),
                    "artifacts": count_for(cur, "strategyos_artifacts", "run_id", run_id),
                    "audit_events": count_for(cur, "strategyos_agent_events", "run_id", run_id),
                    "kg_nodes": count_for(cur, "strategyos_kg_nodes", "run_id", run_id),
                    "kg_edges": count_for(cur, "strategyos_kg_edges", "run_id", run_id),
                }
                return {
                    "status": "ready",
                    "run_id": run_id,
                    "batch_id": str(batch_id),
                    "tenant": tenant_slug,
                    "source_system": source_system_name,
                    "dataset_root": dataset_root,
                    "counts": counts,
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


def insert_run_summary(cur: Any, summary: dict[str, Any]) -> str:
    cur.execute(
        """
        insert into strategyos_runs
            (run_dir, dataset_root, finding_count, locked_finding_count, total_recoverable_sar, summary_json)
        values (%s, %s, %s, %s, %s, %s::jsonb)
        returning id
        """,
        (
            summary["run_dir"],
            summary["dataset"],
            summary["findings"],
            summary["locked_findings"],
            summary["total_recoverable_sar"],
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
    source_uri_map = {Path(item.get("path", "")).name: item.get("uri") for item in summary.get("source_uploads", [])}
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


def persist_finance_records(cur: Any, tenant_id: str, batch_id: str, evidence_ids: dict[str, str], bundle: DataBundle) -> dict[str, int]:
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
    counts["finance_balances"] += persist_cash_forecast(cur, tenant_id, batch_id, evidence_ids, bundle)
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
        amount = money_value(row.get(amount_column)) if amount_column else gl_amount(row)
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
                text_value(row.get(counterparty_column)) if counterparty_column else None,
                date_value(row.get(event_date_column)) if event_date_column else None,
                date_value(row.get(due_date_column)) if due_date_column else None,
                date_value(row.get(settled_date_column)) if settled_date_column else None,
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


def persist_trial_balance(cur: Any, tenant_id: str, batch_id: str, source_document_id: str | None, bundle: DataBundle) -> int:
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


def persist_cash_forecast(cur: Any, tenant_id: str, batch_id: str, evidence_ids: dict[str, str], bundle: DataBundle) -> int:
    count = 0
    source_document_id = evidence_ids.get("07_Cash_Forecast/CFO_Cash_Forecast_June_2026.xlsx")
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
                    money_value(row.get("Balance (SAR)")) or money_value(row.get("H2_Total_LC")),
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


def persist_artifacts(cur: Any, run_id: str, artifacts: dict[str, Path], summary: dict[str, Any]) -> int:
    upload_map = {item.get("artifact"): item.get("uri") for item in summary.get("object_store_uploads", [])}
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


def persist_knowledge_graph(cur: Any, tenant_id: str, run_id: str, knowledge_graph_path: Path | None) -> dict[str, int]:
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


def text_value(value: Any) -> str | None:
    normalized = json_value(value)
    if normalized is None:
        return None
    text = str(normalized).strip()
    return text or None


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
