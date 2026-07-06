from __future__ import annotations

from types import SimpleNamespace

import strategyos_mvp.graph_queries as graph_queries


class FakeResult:
    def __init__(self, records=None, single_record=None):
        self._records = records or []
        self._single = single_record

    def __iter__(self):
        return iter(self._records)

    def single(self):
        return self._single


class FakeSession:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, query: str, **params):
        compact = " ".join(query.split())
        self.calls.append((compact, params))
        if "RETURN count(node) AS node_count" in compact:
            return FakeResult(single_record={"node_count": 4})
        if "rel.original_label IN $relationship_labels" in compact:
            return FakeResult(
                [
                    {
                        "left": _vendor("Vendor:V-1142", "Al Rashid Co"),
                        "right": _vendor("Vendor:V-1187", "Al Rashid Trading"),
                        "relationship_type": "SAME_BANK_ACCOUNT_AS",
                        "findings": [_finding("Finding:F-004", recoverable_sar=104750)],
                        "evidence": [_evidence("03_Master_Data/Vendor_Master.xlsx")],
                    }
                ]
            )
        if "finding.node_key = $finding_node_key" in compact:
            return FakeResult(
                single_record={
                    "finding": _finding("Finding:F-004", recoverable_sar=104750),
                    "evidence": [_evidence("08_Invoices/invoice.pdf")],
                    "vendors": [_vendor("Vendor:V-1142", "Al Rashid Co")],
                    "contracts": [_contract("Contract:04_Contracts/ct.pdf")],
                    "contract_evidence": [_evidence("04_Contracts/ct.pdf")],
                }
            )
        if "vendor.node_key = $vendor_node_key" in compact:
            return FakeResult(
                single_record={
                    "vendor": _vendor("Vendor:V-1142", "Al Rashid Co"),
                    "findings": [_finding("Finding:F-004", recoverable_sar=104750)],
                    "evidence": [_evidence("08_Invoices/invoice.pdf")],
                    "recoverable_sar": 104750.0,
                }
            )
        if "left_finding.node_key < right_finding.node_key" in compact:
            return FakeResult(
                [
                    {
                        "evidence": _evidence("01_Bank_Statements/statement.pdf"),
                        "findings": [
                            _finding("Finding:F-001", recoverable_sar=10),
                            _finding("Finding:F-002", recoverable_sar=20),
                        ],
                    }
                ]
            )
        if "NOT EXISTS" in compact and "HAS_CONTRACT" in compact:
            return FakeResult(
                [
                    {
                        "vendor": _vendor("Vendor:V-2091", "Quick Print Services"),
                        "invoice_count": 11,
                        "invoice_amount_sar": 420200.0,
                    }
                ]
            )
        raise AssertionError(f"Unexpected query: {compact}")


class FakeDriver:
    def __init__(self, session: FakeSession):
        self._session = session

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def session(self):
        return self._session


def _source(session: FakeSession) -> graph_queries.Neo4jGraphSource:
    return graph_queries.Neo4jGraphSource(driver_factory=lambda: FakeDriver(session))


def _vendor(node_key: str, name: str) -> dict:
    return {
        "run_id": "run-1",
        "node_key": node_key,
        "domain_label": "Vendor",
        "vendor_id": node_key.removeprefix("Vendor:"),
        "vendor_name": name,
    }


def _finding(node_key: str, *, recoverable_sar: float) -> dict:
    return {
        "run_id": "run-1",
        "node_key": node_key,
        "domain_label": "Finding",
        "finding_id": node_key.removeprefix("Finding:"),
        "title": f"Finding {node_key}",
        "recoverable_sar": recoverable_sar,
    }


def _evidence(source_path: str) -> dict:
    return {
        "run_id": "run-1",
        "node_key": f"Evidence:{source_path}",
        "domain_label": "Evidence",
        "source_path": source_path,
        "sha256": "abc123",
    }


def _contract(node_key: str) -> dict:
    return {
        "run_id": "run-1",
        "node_key": node_key,
        "domain_label": "Contract",
        "source_path": node_key.removeprefix("Contract:"),
    }


def test_graph_capability_status_degrades_without_run_or_config(monkeypatch):
    monkeypatch.setattr(
        graph_queries,
        "CONFIG",
        SimpleNamespace(neo4j_uri=None),
    )

    assert graph_queries.graph_capability_status(None)["status"] == "missing"
    payload = graph_queries.vendor_collusion_clusters(None)
    assert payload["available"] is False
    assert payload["graph_status"] == "missing"

    payload = graph_queries.graph_capability_status("run-1")
    assert payload["status"] == "skipped"
    assert "NEO4J_URI" in payload["reason"]


def test_graph_capability_status_reports_synced_for_projected_run(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(
        graph_queries,
        "CONFIG",
        SimpleNamespace(neo4j_uri="bolt://neo4j:7687"),
    )
    monkeypatch.setattr(
        graph_queries.neo4j_store,
        "_graph_driver",
        lambda: FakeDriver(session),
    )

    payload = graph_queries.graph_capability_status("run-1")

    assert payload == {"status": "synced", "run_id": "run-1", "node_count": 4}


def test_vendor_collusion_clusters_are_run_scoped_and_cited():
    session = FakeSession()
    result = graph_queries.vendor_collusion_clusters(
        "run-1", source=_source(session), limit=500
    )

    assert result["available"] is True
    assert result["intent"] == "vendor_collusion_cluster"
    assert result["unit"] == "clusters"
    assert result["value"][0]["relationship_type"] == "SAME_BANK_ACCOUNT_AS"
    assert result["value"][0]["left_vendor"]["properties"]["vendor_id"] == "V-1142"
    assert result["citations"][0]["source_path"] == "03_Master_Data/Vendor_Master.xlsx"
    assert "Al Rashid Co" in result["answer"]
    assert "CEO implication" in result["answer"]
    query, params = session.calls[0]
    assert "SAME_BANK_ACCOUNT_AS" not in query
    assert params["relationship_labels"] == ["SAME_BANK_ACCOUNT_AS", "SAME_TAX_ID_AS"]
    assert params["limit"] == graph_queries.MAX_QUERY_LIMIT


def test_vendor_finding_exposure_uses_parameters_for_vendor_input():
    session = FakeSession()
    malicious_vendor = "V-1142'}) DETACH DELETE n //"
    result = graph_queries.vendor_finding_exposure(
        "run-1", malicious_vendor, source=_source(session)
    )

    assert result["available"] is True
    assert result["intent"] == "vendor_finding_exposure"
    assert result["value"]["recoverable_sar"] == 104750.0
    assert result["citations"][0]["source_path"] == "08_Invoices/invoice.pdf"
    query, params = session.calls[0]
    assert malicious_vendor not in query
    assert params["vendor_id"] == malicious_vendor
    assert params["vendor_node_key"] == f"Vendor:{malicious_vendor}"


def test_finding_evidence_chain_returns_cited_chain():
    session = FakeSession()
    result = graph_queries.finding_evidence_chain(
        "run-1", "Finding:F-004", source=_source(session)
    )

    assert result["available"] is True
    assert result["value"]["finding"]["properties"]["finding_id"] == "F-004"
    assert result["value"]["vendors"][0]["id"] == "Vendor:V-1142"
    assert {c["source_path"] for c in result["citations"]} == {
        "08_Invoices/invoice.pdf",
        "04_Contracts/ct.pdf",
    }
    assert "F-004" in result["answer"]
    assert "08_Invoices/invoice.pdf" in result["answer"]
    assert "CEO implication" in result["answer"]
    query, params = session.calls[0]
    assert "Finding:F-004" not in query
    assert params["finding_id"] == "F-004"
    assert params["finding_node_key"] == "Finding:F-004"


def test_shared_evidence_findings_and_contract_gaps_shape_answers():
    shared_session = FakeSession()
    shared = graph_queries.shared_evidence_findings(
        "run-1", source=_source(shared_session)
    )

    assert shared["available"] is True
    assert shared["value"][0]["evidence"]["properties"]["source_path"].endswith(
        "statement.pdf"
    )
    assert len(shared["value"][0]["findings"]) == 2
    assert "F-001" in shared["answer"]

    gap_session = FakeSession()
    gaps = graph_queries.vendor_contract_gaps("run-1", source=_source(gap_session))

    assert gaps["available"] is True
    assert gaps["value"][0]["vendor"]["properties"]["vendor_id"] == "V-2091"
    assert gaps["value"][0]["invoice_count"] == 11
    assert gaps["value"][0]["invoice_amount_sar"] == 420200.0
    assert "Quick Print Services" in gaps["answer"]
    assert "CEO implication" in gaps["answer"]
