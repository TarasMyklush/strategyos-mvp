from __future__ import annotations

import os
import uuid

import pytest

from strategyos_mvp import graph_queries


pytestmark = pytest.mark.skipif(
    not os.environ.get("STRATEGYOS_NEO4J_E2E_URI"),
    reason="Set STRATEGYOS_NEO4J_E2E_URI to run Neo4j graph query e2e tests.",
)


def _driver_factory():
    neo4j = pytest.importorskip("neo4j")
    uri = os.environ["STRATEGYOS_NEO4J_E2E_URI"]
    user = os.environ.get("STRATEGYOS_NEO4J_E2E_USER", "neo4j")
    password = os.environ.get("STRATEGYOS_NEO4J_E2E_PASSWORD", "strategyos")
    return neo4j.GraphDatabase.driver(uri, auth=(user, password))


def test_graph_queries_against_seeded_neo4j_graph():
    run_id = f"graph-query-e2e-{uuid.uuid4()}"
    source = graph_queries.Neo4jGraphSource(driver_factory=_driver_factory)
    driver = _driver_factory()
    try:
        with driver.session() as session:
            _seed_graph(session, run_id)

        collusion = source.vendor_collusion_clusters(run_id)
        assert collusion["value"][0]["left_vendor"]["properties"]["vendor_id"] == "V-1142"
        assert collusion["value"][0]["right_vendor"]["properties"]["vendor_id"] == "V-1187"

        exposure = source.vendor_finding_exposure(run_id, "V-1142")
        assert exposure["value"]["recoverable_sar"] == 104750.0
        assert exposure["value"]["findings"][0]["properties"]["finding_id"] == "F-004"

        chain = source.finding_evidence_chain(run_id, "F-004")
        assert chain["value"]["vendors"][0]["properties"]["vendor_id"] == "V-1142"
        assert {item["source_path"] for item in chain["citations"]} == {
            "08_Invoices/invoice.pdf",
            "04_Contracts/ct.pdf",
        }

        shared = source.shared_evidence_findings(run_id)
        assert shared["value"][0]["evidence"]["properties"]["source_path"] == "08_Invoices/invoice.pdf"
        assert len(shared["value"][0]["findings"]) == 2

        gaps = source.vendor_contract_gaps(run_id)
        assert gaps["value"][0]["vendor"]["properties"]["vendor_id"] == "V-2091"
        assert gaps["value"][0]["invoice_count"] == 1
    finally:
        with driver.session() as session:
            session.run("MATCH (n:StrategyOSNode {run_id: $run_id}) DETACH DELETE n", run_id=run_id)
        driver.close()


def _seed_graph(session, run_id: str) -> None:
    session.run(
        """
        CREATE
          (v1:StrategyOSNode:Vendor {
            run_id: $run_id,
            node_key: 'Vendor:V-1142',
            domain_label: 'Vendor',
            vendor_id: 'V-1142',
            vendor_name: 'Al Rashid Co'
          }),
          (v2:StrategyOSNode:Vendor {
            run_id: $run_id,
            node_key: 'Vendor:V-1187',
            domain_label: 'Vendor',
            vendor_id: 'V-1187',
            vendor_name: 'Al Rashid Trading'
          }),
          (v3:StrategyOSNode:Vendor {
            run_id: $run_id,
            node_key: 'Vendor:V-2091',
            domain_label: 'Vendor',
            vendor_id: 'V-2091',
            vendor_name: 'Quick Print Services'
          }),
          (f4:StrategyOSNode:Finding {
            run_id: $run_id,
            node_key: 'Finding:F-004',
            domain_label: 'Finding',
            finding_id: 'F-004',
            title: 'Duplicate vendor entity resolution',
            recoverable_sar: 104750.0
          }),
          (f5:StrategyOSNode:Finding {
            run_id: $run_id,
            node_key: 'Finding:F-005',
            domain_label: 'Finding',
            finding_id: 'F-005',
            title: 'Shared evidence test',
            recoverable_sar: 0.0
          }),
          (invoice:StrategyOSNode:Invoice {
            run_id: $run_id,
            node_key: 'Invoice:INV-1',
            domain_label: 'Invoice',
            amount_sar: 420200.0
          }),
          (contract:StrategyOSNode:Contract {
            run_id: $run_id,
            node_key: 'Contract:04_Contracts/ct.pdf',
            domain_label: 'Contract',
            source_path: '04_Contracts/ct.pdf'
          }),
          (vendorEvidence:StrategyOSNode:Evidence {
            run_id: $run_id,
            node_key: 'Evidence:03_Master_Data/Vendor_Master.xlsx',
            domain_label: 'Evidence',
            source_path: '03_Master_Data/Vendor_Master.xlsx'
          }),
          (invoiceEvidence:StrategyOSNode:Evidence {
            run_id: $run_id,
            node_key: 'Evidence:08_Invoices/invoice.pdf',
            domain_label: 'Evidence',
            source_path: '08_Invoices/invoice.pdf'
          }),
          (contractEvidence:StrategyOSNode:Evidence {
            run_id: $run_id,
            node_key: 'Evidence:04_Contracts/ct.pdf',
            domain_label: 'Evidence',
            source_path: '04_Contracts/ct.pdf'
          }),
          (v1)-[:SAME_BANK_ACCOUNT_AS {
            run_id: $run_id,
            original_label: 'SAME_BANK_ACCOUNT_AS',
            source_node_key: 'Vendor:V-1142',
            target_node_key: 'Vendor:V-1187'
          }]->(v2),
          (f4)-[:INVOLVES_VENDOR {
            run_id: $run_id,
            original_label: 'INVOLVES_VENDOR'
          }]->(v1),
          (f5)-[:INVOLVES_VENDOR {
            run_id: $run_id,
            original_label: 'INVOLVES_VENDOR'
          }]->(v2),
          (f4)-[:SUPPORTED_BY {
            run_id: $run_id,
            original_label: 'SUPPORTED_BY'
          }]->(invoiceEvidence),
          (f5)-[:SUPPORTED_BY {
            run_id: $run_id,
            original_label: 'SUPPORTED_BY'
          }]->(invoiceEvidence),
          (v1)-[:HAS_CONTRACT {
            run_id: $run_id,
            original_label: 'HAS_CONTRACT'
          }]->(contract),
          (contract)-[:SUPPORTED_BY {
            run_id: $run_id,
            original_label: 'SUPPORTED_BY'
          }]->(contractEvidence),
          (v1)-[:SOURCED_FROM {
            run_id: $run_id,
            original_label: 'SOURCED_FROM'
          }]->(vendorEvidence),
          (v2)-[:SOURCED_FROM {
            run_id: $run_id,
            original_label: 'SOURCED_FROM'
          }]->(vendorEvidence),
          (v3)-[:ISSUED_INVOICE {
            run_id: $run_id,
            original_label: 'ISSUED_INVOICE'
          }]->(invoice)
        """,
        run_id=run_id,
    )
