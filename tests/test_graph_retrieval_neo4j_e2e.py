from __future__ import annotations

import os
import uuid

import pytest

from strategyos_mvp.assistants.graph_retrieval import route_graph_question
from strategyos_mvp import graph_queries
from tests.test_graph_queries_neo4j_e2e import _driver_factory, _seed_graph


pytestmark = pytest.mark.skipif(
    not os.environ.get("STRATEGYOS_NEO4J_E2E_URI"),
    reason="Set STRATEGYOS_NEO4J_E2E_URI to run Neo4j graph retrieval e2e tests.",
)


def test_graph_router_against_seeded_neo4j_graph(monkeypatch):
    run_id = f"graph-router-e2e-{uuid.uuid4()}"
    driver = _driver_factory()
    try:
        with driver.session() as session:
            _seed_graph(session, run_id)
        monkeypatch.setattr(graph_queries.neo4j_store, "_graph_driver", _driver_factory)
        monkeypatch.setattr(graph_queries, "CONFIG", type("Cfg", (), {"neo4j_uri": os.environ["STRATEGYOS_NEO4J_E2E_URI"]})())

        graph_result = route_graph_question(run_id, "show evidence for F-004")

        assert graph_result["matched"] is True
        assert graph_result["answered_by"] == "graph"
        assert graph_result["citations"]
    finally:
        with driver.session() as session:
            session.run("MATCH (n:StrategyOSNode {run_id: $run_id}) DETACH DELETE n", run_id=run_id)
        driver.close()
