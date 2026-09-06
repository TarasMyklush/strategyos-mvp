from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from .config import CONFIG
from .state_store import data_management_status

try:  # pragma: no cover - optional runtime dependency
    from neo4j import GraphDatabase
except Exception:  # pragma: no cover - optional runtime dependency
    GraphDatabase = None  # type: ignore[assignment]


_SAFE_SYMBOL = re.compile(r"[^0-9A-Za-z_]")
_SOURCE_OF_TRUTH_MESSAGE = (
    "Postgres rows plus evidence files remain the durable source of truth; "
    "Neo4j is projection-only."
)


def _status(status: str, **details: Any) -> dict[str, Any]:
    payload = {"status": status}
    payload.update(details)
    return payload


def _sanitize_symbol(value: str, *, prefix: str) -> str:
    cleaned = _SAFE_SYMBOL.sub("_", value.strip())
    if not cleaned:
        return prefix
    if cleaned[0].isdigit():
        return f"{prefix}_{cleaned}"
    return cleaned


def _graph_driver():
    if GraphDatabase is None:
        raise RuntimeError("neo4j driver is not installed.")
    if not CONFIG.neo4j_uri:
        raise RuntimeError("NEO4J_URI is not configured.")
    if not CONFIG.neo4j_user or not CONFIG.neo4j_password:
        raise RuntimeError("NEO4J_USER and NEO4J_PASSWORD are required.")
    return GraphDatabase.driver(
        CONFIG.neo4j_uri,
        auth=(CONFIG.neo4j_user, CONFIG.neo4j_password),
    )


def check_neo4j_ready() -> dict[str, Any]:
    if not CONFIG.neo4j_uri:
        return _status("skipped", reason="NEO4J_URI is not configured.")
    try:
        with _graph_driver() as driver:
            with driver.session() as session:
                result = session.run("RETURN 1 AS ok")
                record = result.single()
        ok = _record_value(record, "ok")
        if ok != 1:
            return _status(
                "failed",
                reason=f"Unexpected Neo4j readiness result: {ok!r}",
            )
        return _status("ok", uri=CONFIG.neo4j_uri, probe="RETURN 1 AS ok")
    except Exception as exc:
        return _status("failed", reason=str(exc))


def project_claim_record(record: Mapping[str, Any], operation: str) -> None:
    """Idempotently project one immutable claim; PostgreSQL remains authority."""
    revision_id = str(record.get("claim_revision_id") or "")
    tenant_id = str(record.get("tenant_id") or "")
    if not revision_id or not tenant_id:
        raise ValueError("Claim graph projection requires tenant and revision IDs.")
    with _graph_driver() as driver:
        with driver.session() as session:
            session.run(
                "CREATE CONSTRAINT strategyos_claim_revision IF NOT EXISTS "
                "FOR (n:StrategyOSClaim) REQUIRE (n.tenant_id, n.claim_revision_id) IS UNIQUE"
            )
            session.run(
                "CREATE CONSTRAINT strategyos_claim_subject IF NOT EXISTS "
                "FOR (n:StrategyOSClaimSubject) REQUIRE (n.tenant_id, n.subject_identity) IS UNIQUE"
            )
            session.run(
                "CREATE CONSTRAINT strategyos_claim_metric IF NOT EXISTS "
                "FOR (n:StrategyOSClaimMetric) REQUIRE (n.tenant_id, n.metric_key) IS UNIQUE"
            )
            session.run(
                "CREATE CONSTRAINT strategyos_claim_source IF NOT EXISTS "
                "FOR (n:StrategyOSClaimSource) REQUIRE (n.tenant_id, n.source_key) IS UNIQUE"
            )
            if operation in {"delete", "revoke"}:
                session.run(
                    "MATCH (c:StrategyOSClaim {tenant_id: $tenant_id, claim_revision_id: $revision_id}) "
                    "DETACH DELETE c",
                    tenant_id=tenant_id,
                    revision_id=revision_id,
                )
                return
            if operation != "upsert":
                raise ValueError(f"Unsupported claim graph operation: {operation!r}")
            subject = record.get("subject") if isinstance(record.get("subject"), dict) else {}
            period = record.get("period") if isinstance(record.get("period"), dict) else {}
            subject_identity = f"{subject.get('type') or 'unknown'}:{subject.get('key') or 'unknown'}"
            properties = {
                "tenant_id": tenant_id,
                "claim_revision_id": revision_id,
                "family_key": str(record.get("family_key") or ""),
                "revision": int(record.get("revision") or 0),
                "label": str(record.get("label") or ""),
                "metric_key": str(record.get("metric_key") or ""),
                "claim_kind": str(record.get("claim_kind") or ""),
                "production_method": str(record.get("production_method") or ""),
                "value": str(record.get("value") or ""),
                "unit": str(record.get("unit") or ""),
                "scale": str(record.get("scale") or "1"),
                "currency": str(record.get("currency") or ""),
                "business_unit": str(record.get("business_unit") or ""),
                "period_start": str(period.get("start") or ""),
                "period_end": str(period.get("end") or ""),
                "as_of": str(period.get("as_of") or ""),
                "scenario": str(record.get("scenario") or ""),
                "traceability": str(record.get("traceability") or ""),
                "projection_only": True,
                "projection_placeholder": False,
            }
            session.run(
                """
                MERGE (c:StrategyOSClaim {tenant_id: $tenant_id, claim_revision_id: $revision_id})
                SET c += $properties
                MERGE (s:StrategyOSClaimSubject {tenant_id: $tenant_id, subject_identity: $subject_identity})
                SET s.subject_type = $subject_type, s.subject_key = $subject_key
                MERGE (m:StrategyOSClaimMetric {tenant_id: $tenant_id, metric_key: $metric_key})
                MERGE (c)-[:ASSERTS_ABOUT]->(s)
                MERGE (c)-[:MEASURES]->(m)
                """,
                tenant_id=tenant_id,
                revision_id=revision_id,
                properties=properties,
                subject_identity=subject_identity,
                subject_type=str(subject.get("type") or "unknown"),
                subject_key=str(subject.get("key") or "unknown"),
                metric_key=str(record.get("metric_key") or "unknown"),
            )
            for source in list(record.get("sources") or []):
                if not isinstance(source, dict) or not source.get("source_key"):
                    continue
                session.run(
                    """
                    MATCH (c:StrategyOSClaim {tenant_id: $tenant_id, claim_revision_id: $revision_id})
                    MERGE (s:StrategyOSClaimSource {tenant_id: $tenant_id, source_key: $source_key})
                    SET s.display_name = $display_name,
                        s.origin_category = $origin_category,
                        s.capture_method = $capture_method,
                        s.provider_name = $provider_name
                    MERGE (c)-[r:SUPPORTED_BY {occurrence_key: $occurrence_key}]->(s)
                    SET r.locator = $locator
                    """,
                    tenant_id=tenant_id,
                    revision_id=revision_id,
                    source_key=str(source["source_key"]),
                    display_name=str(source.get("display_name") or ""),
                    origin_category=str(source.get("origin_category") or "unknown"),
                    capture_method=str(source.get("capture_method") or "unknown"),
                    provider_name=str(source.get("provider_name") or ""),
                    occurrence_key=str(source.get("occurrence_key") or "inherited"),
                    locator=str(source.get("locator") or ""),
                )
            formula = record.get("formula") if isinstance(record.get("formula"), dict) else {}
            for input_revision_id in list(formula.get("inputs") or []):
                session.run(
                    """
                    MATCH (c:StrategyOSClaim {tenant_id: $tenant_id, claim_revision_id: $revision_id})
                    MERGE (i:StrategyOSClaim {tenant_id: $tenant_id, claim_revision_id: $input_revision_id})
                    ON CREATE SET i.projection_placeholder = true, i.projection_only = true
                    MERGE (c)-[:CALCULATED_FROM]->(i)
                    """,
                    tenant_id=tenant_id,
                    revision_id=revision_id,
                    input_revision_id=str(input_revision_id),
                )


def sync_knowledge_graph(
    *,
    run_id: str | None,
    tenant_slug: str,
    knowledge_graph_path: Path | None,
    authoritative_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not run_id:
        return _status("skipped", reason="run_id is unavailable.")
    if not knowledge_graph_path:
        return _status(
            "missing", run_id=run_id, reason="Knowledge graph path is unavailable."
        )
    if not knowledge_graph_path.exists():
        return _status(
            "missing",
            run_id=run_id,
            graph_path=str(knowledge_graph_path),
            reason="Knowledge graph artifact does not exist.",
        )
    if not CONFIG.neo4j_uri:
        return _status("skipped", run_id=run_id, reason="NEO4J_URI is not configured.")

    from .access_scope import source_index_allowed
    if not source_index_allowed(run_id, tenant_slug):
        return _status("blocked", run_id=run_id, reason="Source policy does not permit this bulk graph index.")

    graph = json.loads(knowledge_graph_path.read_text(encoding="utf-8"))
    source_counts = _graph_source_counts(graph)
    projection_guardrails = _projection_guardrails(
        run_id=run_id,
        knowledge_graph_path=knowledge_graph_path,
        source_counts=source_counts,
        authoritative_status=authoritative_status,
    )
    if projection_guardrails["status"] != "ok":
        return _status(
            "blocked",
            run_id=run_id,
            graph_path=str(knowledge_graph_path),
            source_counts=source_counts,
            reason=projection_guardrails["reason"],
            projection_guardrails=projection_guardrails,
        )
    with _graph_driver() as driver:
        with driver.session() as session:
            _ensure_schema(session)
            session.run(
                "MATCH ()-[r]->() WHERE r.run_id = $run_id DELETE r",
                run_id=run_id,
            )
            session.run(
                "MATCH (n:StrategyOSNode {run_id: $run_id}) DETACH DELETE n",
                run_id=run_id,
            )
            for node in graph.get("nodes", []):
                _upsert_node(session, run_id, tenant_slug, node)
            for edge in graph.get("edges", []):
                _upsert_edge(session, run_id, edge)
            summary = _graph_summary(session, run_id)

    return {
        "status": "synced",
        "run_id": run_id,
        "graph_path": str(knowledge_graph_path),
        "source_counts": source_counts,
        "projection_guardrails": projection_guardrails,
        **summary,
    }


def graph_status_for_run(run_id: str | None) -> dict[str, Any]:
    if not run_id:
        return _status("missing", reason="No run_id is available for Neo4j lookup.")
    if not CONFIG.neo4j_uri:
        return _status("skipped", run_id=run_id, reason="NEO4J_URI is not configured.")
    from .access_scope import source_index_allowed, principal_scope
    tenant_id = str((principal_scope.get() or {}).get("tenant_id") or getattr(CONFIG, "tenant_slug", ""))
    if not source_index_allowed(run_id, tenant_id):
        return _status("blocked", run_id=run_id, reason="Current source permissions do not permit this graph index.")
    try:
        with _graph_driver() as driver:
            with driver.session() as session:
                summary = _graph_summary(session, run_id)
        authoritative_status = data_management_status(run_id)
        graph_path = _knowledge_graph_path(authoritative_status)
        source_counts = _graph_counts_from_file(graph_path)
        projection_guardrails = _projection_guardrails(
            run_id=run_id,
            knowledge_graph_path=graph_path,
            source_counts=source_counts,
            authoritative_status=authoritative_status,
        )
        node_count = int(summary.get("node_count", 0) or 0)
        edge_count = int(summary.get("edge_count", 0) or 0)
        status = "ready" if node_count > 0 or edge_count > 0 else "empty"
        reason = None
        if status == "empty":
            reason = "No graph nodes or relationships have been projected for this run yet."
        if status == "ready" and projection_guardrails["status"] != "ok":
            status = "failed"
            reason = projection_guardrails["reason"]
        payload = {
            "status": status,
            "run_id": run_id,
            "projection_guardrails": projection_guardrails,
            **summary,
        }
        if source_counts is not None:
            payload["source_counts"] = source_counts
        if reason:
            payload["reason"] = reason
        return payload
    except Exception as exc:
        return _status("failed", run_id=run_id, reason=str(exc))


def _graph_source_counts(graph: dict[str, Any]) -> dict[str, int]:
    return {
        "nodes": len(graph.get("nodes", [])),
        "edges": len(graph.get("edges", [])),
    }


def _graph_counts_from_file(knowledge_graph_path: Path | None) -> dict[str, int] | None:
    if knowledge_graph_path is None or not knowledge_graph_path.exists():
        return None
    graph = json.loads(knowledge_graph_path.read_text(encoding="utf-8"))
    return _graph_source_counts(graph)


def _knowledge_graph_path(authoritative_status: dict[str, Any] | None) -> Path | None:
    if not authoritative_status:
        return None
    artifact_path = (authoritative_status.get("artifacts") or {}).get("knowledge_graph")
    if not artifact_path:
        return None
    return Path(str(artifact_path))


def _projection_guardrails(
    *,
    run_id: str,
    knowledge_graph_path: Path | None,
    source_counts: dict[str, int] | None,
    authoritative_status: dict[str, Any] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "ok",
        "policy": _SOURCE_OF_TRUTH_MESSAGE,
        "projection_store": "neo4j",
        "durable_sources": ["postgres", "evidence_files"],
        "run_id": run_id,
        "requires_authoritative_postgres": True,
        "requires_evidence_file": True,
    }
    if knowledge_graph_path is not None:
        payload["knowledge_graph_path"] = str(knowledge_graph_path)
        payload["evidence_file_exists"] = knowledge_graph_path.exists()
    if source_counts is not None:
        payload["source_counts"] = source_counts

    if authoritative_status is None:
        return _guardrail_failure(payload, "Authoritative Postgres status is unavailable.")

    payload["postgres_status"] = authoritative_status.get("status")
    postgres_counts = _authoritative_graph_counts(authoritative_status)
    if postgres_counts is not None:
        payload["postgres_counts"] = postgres_counts

    authoritative_ok = authoritative_status.get("status") in {"persisted", "ready"}
    if not authoritative_ok:
        return _guardrail_failure(
            payload,
            "Neo4j projection requires a persisted Postgres source-of-truth record first.",
        )
    if knowledge_graph_path is None or not knowledge_graph_path.exists():
        return _guardrail_failure(
            payload,
            "Neo4j projection requires the knowledge-graph evidence file to exist.",
        )
    if postgres_counts is None:
        return _guardrail_failure(
            payload,
            "Neo4j projection requires Postgres knowledge-graph counts for verification.",
        )
    if source_counts is None:
        return _guardrail_failure(
            payload,
            "Neo4j projection requires readable knowledge-graph evidence counts.",
        )
    counts_match = postgres_counts == source_counts
    payload["counts_match"] = counts_match
    if not counts_match:
        return _guardrail_failure(
            payload,
            "Neo4j projection is blocked because Postgres and evidence-file graph counts diverge.",
        )
    return payload


def _authoritative_graph_counts(
    authoritative_status: dict[str, Any] | None,
) -> dict[str, int] | None:
    if not authoritative_status:
        return None
    counts = authoritative_status.get("data_management") or authoritative_status.get("counts")
    if not isinstance(counts, dict):
        return None
    if "kg_nodes" not in counts or "kg_edges" not in counts:
        return None
    return {
        "nodes": int(counts.get("kg_nodes", 0) or 0),
        "edges": int(counts.get("kg_edges", 0) or 0),
    }


def _guardrail_failure(payload: dict[str, Any], reason: str) -> dict[str, Any]:
    payload["status"] = "blocked"
    payload["reason"] = reason
    return payload


def _ensure_schema(session: Any) -> None:
    statements = [
        "CREATE CONSTRAINT strategyos_node_identity IF NOT EXISTS FOR (n:StrategyOSNode) REQUIRE (n.run_id, n.node_key) IS UNIQUE",
        "CREATE INDEX strategyos_node_run_id IF NOT EXISTS FOR (n:StrategyOSNode) ON (n.run_id)",
        "CREATE INDEX strategyos_node_label IF NOT EXISTS FOR (n:StrategyOSNode) ON (n.domain_label)",
    ]
    for statement in statements:
        session.run(statement)


def _upsert_node(
    session: Any, run_id: str, tenant_slug: str, node: dict[str, Any]
) -> None:
    domain_label = _sanitize_symbol(str(node.get("label") or "Unknown"), prefix="Label")
    properties = dict(node.get("properties") or {})
    properties.update(
        {
            "run_id": run_id,
            "tenant_slug": tenant_slug,
            "node_key": str(node["id"]),
            "domain_label": str(node.get("label") or "Unknown"),
        }
    )
    session.run(
        f"""
        MERGE (n:StrategyOSNode:{domain_label} {{run_id: $run_id, node_key: $node_key}})
        SET n += $properties
        """,
        run_id=run_id,
        node_key=str(node["id"]),
        properties=properties,
    )


def _upsert_edge(session: Any, run_id: str, edge: dict[str, Any]) -> None:
    relation_type = _sanitize_symbol(
        str(edge.get("label") or "RELATED_TO"),
        prefix="REL",
    )
    properties = dict(edge.get("properties") or {})
    properties.update(
        {
            "run_id": run_id,
            "source_node_key": str(edge.get("source") or ""),
            "target_node_key": str(edge.get("target") or ""),
            "original_label": str(edge.get("label") or "RELATED_TO"),
        }
    )
    session.run(
        f"""
        MATCH (source:StrategyOSNode {{run_id: $run_id, node_key: $source_node_key}})
        MATCH (target:StrategyOSNode {{run_id: $run_id, node_key: $target_node_key}})
        MERGE (source)-[r:{relation_type} {{
            run_id: $run_id,
            source_node_key: $source_node_key,
            target_node_key: $target_node_key,
            original_label: $original_label
        }}]->(target)
        SET r += $properties
        """,
        run_id=run_id,
        source_node_key=str(edge.get("source") or ""),
        target_node_key=str(edge.get("target") or ""),
        original_label=str(edge.get("label") or "RELATED_TO"),
        properties=properties,
    )


def _graph_summary(session: Any, run_id: str) -> dict[str, Any]:
    node_record = session.run(
        "MATCH (n:StrategyOSNode {run_id: $run_id}) RETURN count(n) AS node_count",
        run_id=run_id,
    ).single()
    edge_record = session.run(
        "MATCH (:StrategyOSNode {run_id: $run_id})-[r]->(:StrategyOSNode {run_id: $run_id}) RETURN count(r) AS edge_count",
        run_id=run_id,
    ).single()
    sample_record = session.run(
        """
        MATCH (source:StrategyOSNode:Finding {run_id: $run_id})-[r]->(target:StrategyOSNode:Vendor {run_id: $run_id})
        RETURN source.node_key AS source_node_key,
               type(r) AS relationship_type,
               target.node_key AS target_node_key,
               r.original_label AS original_label
        LIMIT 1
        """,
        run_id=run_id,
    ).single()
    return {
        "node_count": int(_record_value(node_record, "node_count") or 0),
        "edge_count": int(_record_value(edge_record, "edge_count") or 0),
        "sample_relation": (
            None
            if sample_record is None
            else {
                "source_node_key": _record_value(sample_record, "source_node_key"),
                "relationship_type": _record_value(sample_record, "relationship_type"),
                "target_node_key": _record_value(sample_record, "target_node_key"),
                "original_label": _record_value(sample_record, "original_label"),
            }
        ),
    }


def _record_value(record: Any, key: str) -> Any:
    if record is None:
        return None
    if isinstance(record, dict):
        return record.get(key)
    return record[key]
