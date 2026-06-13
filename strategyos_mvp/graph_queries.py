from __future__ import annotations

from typing import Any, Callable, Protocol

from .config import CONFIG
from . import neo4j_store


MAX_QUERY_LIMIT = 100
DEFAULT_QUERY_LIMIT = 25
ENTITY_RESOLUTION_RELATIONSHIPS = ("SAME_BANK_ACCOUNT_AS", "SAME_TAX_ID_AS")


class GraphQuerySource(Protocol):
    def vendor_collusion_clusters(
        self, run_id: str, *, limit: int = DEFAULT_QUERY_LIMIT
    ) -> dict[str, Any]:
        ...

    def finding_evidence_chain(
        self, run_id: str, finding_id: str, *, limit: int = DEFAULT_QUERY_LIMIT
    ) -> dict[str, Any]:
        ...

    def vendor_finding_exposure(
        self, run_id: str, vendor_id: str, *, limit: int = DEFAULT_QUERY_LIMIT
    ) -> dict[str, Any]:
        ...

    def shared_evidence_findings(
        self, run_id: str, *, limit: int = DEFAULT_QUERY_LIMIT
    ) -> dict[str, Any]:
        ...

    def vendor_contract_gaps(
        self, run_id: str, *, limit: int = DEFAULT_QUERY_LIMIT
    ) -> dict[str, Any]:
        ...


class Neo4jGraphSource:
    def __init__(self, driver_factory: Callable[[], Any] | None = None) -> None:
        self._driver_factory = driver_factory

    def _driver(self) -> Any:
        if self._driver_factory is not None:
            return self._driver_factory()
        return neo4j_store._graph_driver()

    def vendor_collusion_clusters(
        self, run_id: str, *, limit: int = DEFAULT_QUERY_LIMIT
    ) -> dict[str, Any]:
        rows = self._read(
            """
            MATCH (left:StrategyOSNode {run_id: $run_id, domain_label: 'Vendor'})-[rel]->(right:StrategyOSNode {run_id: $run_id, domain_label: 'Vendor'})
            WHERE rel.run_id = $run_id
              AND rel.original_label IN $relationship_labels
              AND left.node_key < right.node_key
            OPTIONAL MATCH (finding:StrategyOSNode {run_id: $run_id, domain_label: 'Finding'})-[involves]->(vendor:StrategyOSNode {run_id: $run_id, domain_label: 'Vendor'})
            WHERE involves.original_label = 'INVOLVES_VENDOR'
              AND vendor.node_key IN [left.node_key, right.node_key]
            OPTIONAL MATCH (left)-[left_source]->(left_evidence:StrategyOSNode {run_id: $run_id, domain_label: 'Evidence'})
            WHERE left_source.original_label = 'SOURCED_FROM'
            OPTIONAL MATCH (right)-[right_source]->(right_evidence:StrategyOSNode {run_id: $run_id, domain_label: 'Evidence'})
            WHERE right_source.original_label = 'SOURCED_FROM'
            RETURN left,
                   right,
                   rel.original_label AS relationship_type,
                   collect(DISTINCT finding) AS findings,
                   collect(DISTINCT left_evidence) + collect(DISTINCT right_evidence) AS evidence
            ORDER BY relationship_type, left.node_key, right.node_key
            LIMIT $limit
            """,
            run_id=run_id,
            relationship_labels=list(ENTITY_RESOLUTION_RELATIONSHIPS),
            limit=_bounded_limit(limit),
        )
        clusters = []
        citations = []
        for row in rows:
            evidence = _nodes(row.get("evidence"))
            citations.extend(_citations(evidence))
            clusters.append(
                {
                    "left_vendor": _node_summary(row.get("left")),
                    "right_vendor": _node_summary(row.get("right")),
                    "relationship_type": row.get("relationship_type"),
                    "findings": _nodes(row.get("findings")),
                    "citations": _citations(evidence),
                }
            )
        return {
            "matched": True,
            "available": True,
            "intent": "vendor_collusion_cluster",
            "answer": (
                f"Found {len(clusters)} vendor entity-resolution cluster(s) with shared bank-account or tax-id edges."
            ),
            "value": clusters,
            "unit": "clusters",
            "basis": "Neo4j run-scoped traversal of Vendor SAME_BANK_ACCOUNT_AS/SAME_TAX_ID_AS relationships.",
            "citations": _dedupe_citations(citations),
        }

    def finding_evidence_chain(
        self, run_id: str, finding_id: str, *, limit: int = DEFAULT_QUERY_LIMIT
    ) -> dict[str, Any]:
        normalized_finding_id = _strip_prefix(finding_id, "Finding:")
        row = self._single(
            """
            MATCH (finding:StrategyOSNode {run_id: $run_id, domain_label: 'Finding'})
            WHERE finding.node_key = $finding_node_key OR finding.finding_id = $finding_id
            OPTIONAL MATCH (finding)-[support]->(evidence:StrategyOSNode {run_id: $run_id, domain_label: 'Evidence'})
            WHERE support.original_label = 'SUPPORTED_BY'
            OPTIONAL MATCH (finding)-[involves]->(vendor:StrategyOSNode {run_id: $run_id, domain_label: 'Vendor'})
            WHERE involves.original_label = 'INVOLVES_VENDOR'
            OPTIONAL MATCH (vendor)-[contract_rel]->(contract:StrategyOSNode {run_id: $run_id, domain_label: 'Contract'})
            WHERE contract_rel.original_label = 'HAS_CONTRACT'
            OPTIONAL MATCH (contract)-[contract_support]->(contract_evidence:StrategyOSNode {run_id: $run_id, domain_label: 'Evidence'})
            WHERE contract_support.original_label = 'SUPPORTED_BY'
            RETURN finding,
                   collect(DISTINCT evidence)[0..$limit] AS evidence,
                   collect(DISTINCT vendor)[0..$limit] AS vendors,
                   collect(DISTINCT contract)[0..$limit] AS contracts,
                   collect(DISTINCT contract_evidence)[0..$limit] AS contract_evidence
            LIMIT 1
            """,
            run_id=run_id,
            finding_id=normalized_finding_id,
            finding_node_key=f"Finding:{normalized_finding_id}",
            limit=_bounded_limit(limit),
        )
        if not row:
            return _empty_answer(
                intent="finding_evidence_chain",
                answer=f"No Neo4j evidence chain was found for finding {normalized_finding_id}.",
                unit="chains",
            )
        evidence = _nodes(row.get("evidence")) + _nodes(row.get("contract_evidence"))
        vendors = _nodes(row.get("vendors"))
        contracts = _nodes(row.get("contracts"))
        finding = _node_summary(row.get("finding"))
        return {
            "matched": True,
            "available": True,
            "intent": "finding_evidence_chain",
            "answer": (
                f"{normalized_finding_id} is connected to {len(_nodes(row.get('evidence')))} direct evidence source(s), "
                f"{len(vendors)} vendor(s), and {len(contracts)} contract node(s)."
            ),
            "value": {
                "finding": finding,
                "evidence": _dedupe_nodes(evidence),
                "vendors": vendors,
                "contracts": contracts,
            },
            "unit": "chain",
            "basis": "Neo4j run-scoped traversal from Finding to SUPPORTED_BY evidence and INVOLVES_VENDOR/HAS_CONTRACT context.",
            "citations": _dedupe_citations(_citations(evidence)),
        }

    def vendor_finding_exposure(
        self, run_id: str, vendor_id: str, *, limit: int = DEFAULT_QUERY_LIMIT
    ) -> dict[str, Any]:
        normalized_vendor_id = _strip_prefix(vendor_id, "Vendor:")
        row = self._single(
            """
            MATCH (finding:StrategyOSNode {run_id: $run_id, domain_label: 'Finding'})-[involves]->(vendor:StrategyOSNode {run_id: $run_id, domain_label: 'Vendor'})
            WHERE involves.original_label = 'INVOLVES_VENDOR'
              AND (vendor.node_key = $vendor_node_key OR vendor.vendor_id = $vendor_id)
            WITH vendor, collect(DISTINCT finding)[0..$limit] AS findings
            OPTIONAL MATCH (linked_finding:StrategyOSNode {run_id: $run_id, domain_label: 'Finding'})-[support]->(evidence:StrategyOSNode {run_id: $run_id, domain_label: 'Evidence'})
            WHERE linked_finding IN findings AND support.original_label = 'SUPPORTED_BY'
            RETURN vendor,
                   findings,
                   collect(DISTINCT evidence)[0..$limit] AS evidence,
                   reduce(total = 0.0, item IN findings | total + coalesce(toFloat(item.recoverable_sar), 0.0)) AS recoverable_sar
            LIMIT 1
            """,
            run_id=run_id,
            vendor_id=normalized_vendor_id,
            vendor_node_key=f"Vendor:{normalized_vendor_id}",
            limit=_bounded_limit(limit),
        )
        if not row:
            return _empty_answer(
                intent="vendor_finding_exposure",
                answer=f"No Neo4j findings were linked to vendor {normalized_vendor_id}.",
                unit="findings",
            )
        findings = _nodes(row.get("findings"))
        evidence = _nodes(row.get("evidence"))
        recoverable_sar = _as_float(row.get("recoverable_sar"))
        return {
            "matched": True,
            "available": True,
            "intent": "vendor_finding_exposure",
            "answer": (
                f"Vendor {normalized_vendor_id} is linked to {len(findings)} finding(s) with {_sar(recoverable_sar)} recoverable."
            ),
            "value": {
                "vendor": _node_summary(row.get("vendor")),
                "findings": findings,
                "recoverable_sar": round(recoverable_sar, 2),
            },
            "unit": "SAR",
            "basis": "Neo4j run-scoped traversal from Finding INVOLVES_VENDOR to the requested vendor.",
            "citations": _dedupe_citations(_citations(evidence)),
        }

    def shared_evidence_findings(
        self, run_id: str, *, limit: int = DEFAULT_QUERY_LIMIT
    ) -> dict[str, Any]:
        rows = self._read(
            """
            MATCH (left_finding:StrategyOSNode {run_id: $run_id, domain_label: 'Finding'})-[left_support]->(evidence:StrategyOSNode {run_id: $run_id, domain_label: 'Evidence'})<-[right_support]-(right_finding:StrategyOSNode {run_id: $run_id, domain_label: 'Finding'})
            WHERE left_support.original_label = 'SUPPORTED_BY'
              AND right_support.original_label = 'SUPPORTED_BY'
              AND left_finding.node_key < right_finding.node_key
            WITH evidence, collect(DISTINCT left_finding) + collect(DISTINCT right_finding) AS findings
            RETURN evidence, findings
            ORDER BY evidence.source_path
            LIMIT $limit
            """,
            run_id=run_id,
            limit=_bounded_limit(limit),
        )
        groups = []
        citations = []
        for row in rows:
            evidence = _node_summary(row.get("evidence"))
            findings = _dedupe_nodes(_nodes(row.get("findings")))
            citations.extend(_citations([evidence]))
            groups.append({"evidence": evidence, "findings": findings})
        return {
            "matched": True,
            "available": True,
            "intent": "shared_evidence_findings",
            "answer": f"Found {len(groups)} evidence source(s) shared by multiple findings.",
            "value": groups,
            "unit": "evidence_sources",
            "basis": "Neo4j run-scoped traversal of Finding SUPPORTED_BY Evidence pairs.",
            "citations": _dedupe_citations(citations),
        }

    def vendor_contract_gaps(
        self, run_id: str, *, limit: int = DEFAULT_QUERY_LIMIT
    ) -> dict[str, Any]:
        rows = self._read(
            """
            MATCH (vendor:StrategyOSNode {run_id: $run_id, domain_label: 'Vendor'})
            WHERE EXISTS {
                MATCH (vendor)-[invoice_rel]->(:StrategyOSNode {run_id: $run_id, domain_label: 'Invoice'})
                WHERE invoice_rel.original_label = 'ISSUED_INVOICE'
            }
            AND NOT EXISTS {
                MATCH (vendor)-[contract_rel]->(:StrategyOSNode {run_id: $run_id, domain_label: 'Contract'})
                WHERE contract_rel.original_label = 'HAS_CONTRACT'
            }
            OPTIONAL MATCH (vendor)-[invoice_rel]->(invoice:StrategyOSNode {run_id: $run_id, domain_label: 'Invoice'})
            WHERE invoice_rel.original_label = 'ISSUED_INVOICE'
            WITH vendor, count(invoice) AS invoice_count, sum(toFloat(coalesce(invoice.amount_sar, 0))) AS invoice_amount_sar
            RETURN vendor, invoice_count, invoice_amount_sar
            ORDER BY invoice_amount_sar DESC, vendor.node_key
            LIMIT $limit
            """,
            run_id=run_id,
            limit=_bounded_limit(limit),
        )
        vendors = [
            {
                "vendor": _node_summary(row.get("vendor")),
                "invoice_count": int(row.get("invoice_count") or 0),
                "invoice_amount_sar": round(_as_float(row.get("invoice_amount_sar")), 2),
            }
            for row in rows
        ]
        return {
            "matched": True,
            "available": True,
            "intent": "vendor_contract_gap",
            "answer": f"Found {len(vendors)} vendor(s) with invoices and no HAS_CONTRACT edge.",
            "value": vendors,
            "unit": "vendors",
            "basis": "Neo4j run-scoped traversal for vendors issuing invoices without a contract relationship.",
            "citations": [],
        }

    def _read(self, query: str, **params: Any) -> list[dict[str, Any]]:
        with self._driver() as driver:
            with driver.session() as session:
                return [_record_to_dict(record) for record in session.run(query, **params)]

    def _single(self, query: str, **params: Any) -> dict[str, Any] | None:
        with self._driver() as driver:
            with driver.session() as session:
                record = session.run(query, **params).single()
        return None if record is None else _record_to_dict(record)


def graph_capability_status(run_id: str | None) -> dict[str, Any]:
    if not run_id:
        return {"status": "missing", "reason": "No run_id is available for Neo4j graph queries."}
    if not CONFIG.neo4j_uri:
        return {
            "status": "skipped",
            "run_id": run_id,
            "reason": "NEO4J_URI is not configured.",
        }
    try:
        with neo4j_store._graph_driver() as driver:
            with driver.session() as session:
                record = session.run(
                    "MATCH (node:StrategyOSNode {run_id: $run_id}) RETURN count(node) AS node_count",
                    run_id=run_id,
                ).single()
        node_count = int(_record_value(record, "node_count") or 0)
        if node_count <= 0:
            return {
                "status": "empty",
                "run_id": run_id,
                "node_count": 0,
                "reason": "No Neo4j graph nodes have been projected for this run yet.",
            }
        return {"status": "synced", "run_id": run_id, "node_count": node_count}
    except Exception as exc:
        return {"status": "failed", "run_id": run_id, "reason": str(exc)}


def vendor_collusion_clusters(
    run_id: str | None,
    *,
    limit: int = DEFAULT_QUERY_LIMIT,
    source: GraphQuerySource | None = None,
) -> dict[str, Any]:
    return _with_source(
        run_id,
        "vendor_collusion_cluster",
        source,
        lambda graph_source, actual_run_id: graph_source.vendor_collusion_clusters(
            actual_run_id, limit=limit
        ),
    )


def finding_evidence_chain(
    run_id: str | None,
    finding_id: str,
    *,
    limit: int = DEFAULT_QUERY_LIMIT,
    source: GraphQuerySource | None = None,
) -> dict[str, Any]:
    return _with_source(
        run_id,
        "finding_evidence_chain",
        source,
        lambda graph_source, actual_run_id: graph_source.finding_evidence_chain(
            actual_run_id, finding_id, limit=limit
        ),
    )


def vendor_finding_exposure(
    run_id: str | None,
    vendor_id: str,
    *,
    limit: int = DEFAULT_QUERY_LIMIT,
    source: GraphQuerySource | None = None,
) -> dict[str, Any]:
    return _with_source(
        run_id,
        "vendor_finding_exposure",
        source,
        lambda graph_source, actual_run_id: graph_source.vendor_finding_exposure(
            actual_run_id, vendor_id, limit=limit
        ),
    )


def shared_evidence_findings(
    run_id: str | None,
    *,
    limit: int = DEFAULT_QUERY_LIMIT,
    source: GraphQuerySource | None = None,
) -> dict[str, Any]:
    return _with_source(
        run_id,
        "shared_evidence_findings",
        source,
        lambda graph_source, actual_run_id: graph_source.shared_evidence_findings(
            actual_run_id, limit=limit
        ),
    )


def vendor_contract_gaps(
    run_id: str | None,
    *,
    limit: int = DEFAULT_QUERY_LIMIT,
    source: GraphQuerySource | None = None,
) -> dict[str, Any]:
    return _with_source(
        run_id,
        "vendor_contract_gap",
        source,
        lambda graph_source, actual_run_id: graph_source.vendor_contract_gaps(
            actual_run_id, limit=limit
        ),
    )


def _with_source(
    run_id: str | None,
    intent: str,
    source: GraphQuerySource | None,
    fn: Callable[[GraphQuerySource, str], dict[str, Any]],
) -> dict[str, Any]:
    if not run_id:
        return _unavailable(
            intent=intent,
            status="missing",
            reason="No run_id is available for Neo4j graph queries.",
        )
    graph_source = source
    if graph_source is None:
        status = graph_capability_status(run_id)
        if status.get("status") != "synced":
            return _unavailable(
                intent=intent,
                status=str(status.get("status") or "failed"),
                reason=str(status.get("reason") or "Neo4j graph is not available for this run."),
                details=status,
            )
        graph_source = Neo4jGraphSource()
    try:
        return fn(graph_source, run_id)
    except Exception as exc:
        return _unavailable(intent=intent, status="failed", reason=str(exc))


def _unavailable(
    *, intent: str, status: str, reason: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "matched": True,
        "available": False,
        "intent": intent,
        "answer": "Neo4j graph queries are not available for this run.",
        "value": None,
        "unit": None,
        "basis": reason,
        "citations": [],
        "graph_status": status,
    }
    if details is not None:
        payload["graph_status_details"] = details
    return payload


def _empty_answer(*, intent: str, answer: str, unit: str) -> dict[str, Any]:
    return {
        "matched": True,
        "available": True,
        "intent": intent,
        "answer": answer,
        "value": [],
        "unit": unit,
        "basis": "Neo4j run-scoped graph query returned no rows.",
        "citations": [],
    }


def _bounded_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = DEFAULT_QUERY_LIMIT
    return max(1, min(MAX_QUERY_LIMIT, value))


def _strip_prefix(value: str, prefix: str) -> str:
    text = str(value or "").strip()
    if text.startswith(prefix):
        return text[len(prefix) :]
    return text


def _record_to_dict(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        return dict(record)
    try:
        return dict(record.items())
    except AttributeError:
        return {key: record[key] for key in record.keys()}


def _record_value(record: Any, key: str) -> Any:
    if record is None:
        return None
    if isinstance(record, dict):
        return record.get(key)
    return record[key]


def _entity_properties(entity: Any) -> dict[str, Any]:
    if entity is None:
        return {}
    if isinstance(entity, dict):
        return dict(entity)
    try:
        return dict(entity.items())
    except AttributeError:
        return dict(entity)


def _nodes(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    return [_node_summary(item) for item in value if item is not None]


def _node_summary(entity: Any) -> dict[str, Any]:
    props = _entity_properties(entity)
    node_key = str(props.get("node_key") or props.get("id") or "")
    label = str(props.get("domain_label") or props.get("label") or "")
    display = (
        props.get("title")
        or props.get("vendor_name")
        or props.get("source_path")
        or props.get("invoice_id")
        or props.get("po_id")
        or props.get("contract_reference")
        or node_key
    )
    return {
        "id": node_key,
        "label": label,
        "display": display,
        "properties": props,
    }


def _dedupe_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for node in nodes:
        node_id = str(node.get("id") or "")
        if node_id in seen:
            continue
        seen.add(node_id)
        deduped.append(node)
    return deduped


def _citations(evidence_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citations = []
    for node in evidence_nodes:
        props = node.get("properties") or {}
        source_path = props.get("source_path")
        if not source_path and str(node.get("id") or "").startswith("Evidence:"):
            source_path = str(node["id"])[len("Evidence:") :]
        if not source_path:
            continue
        citations.append(
            {
                "source_path": source_path,
                "locator": props.get("locator") or "",
                "excerpt": "",
                "source_hash": props.get("sha256"),
            }
        )
    return citations


def _dedupe_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for citation in citations:
        key = (str(citation.get("source_path") or ""), str(citation.get("locator") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(citation)
    return deduped


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _sar(value: float) -> str:
    return f"SAR {value:,.2f}"
