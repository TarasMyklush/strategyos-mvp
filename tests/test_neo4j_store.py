from __future__ import annotations

import json
from types import SimpleNamespace

import strategyos_mvp.api as api_module
import strategyos_mvp.neo4j_store as neo4j_store


class FakeResult:
    def __init__(self, record):
        self._record = record

    def single(self):
        return self._record


class FakeSession:
    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple[str, str, str], dict] = {}
        self.statements: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, query: str, **params):
        compact = " ".join(query.split())
        self.statements.append(compact)
        if compact == "RETURN 1 AS ok":
            return FakeResult({"ok": 1})
        if compact.startswith("CREATE CONSTRAINT") or compact.startswith(
            "CREATE INDEX"
        ):
            return FakeResult(None)
        if compact.startswith("MATCH ()-[r]->() WHERE r.run_id = $run_id DELETE r"):
            run_id = params["run_id"]
            self.edges = {
                key: value
                for key, value in self.edges.items()
                if value.get("run_id") != run_id
            }
            return FakeResult(None)
        if compact.startswith(
            "MATCH (n:StrategyOSNode {run_id: $run_id}) DETACH DELETE n"
        ):
            run_id = params["run_id"]
            self.nodes = {
                key: value
                for key, value in self.nodes.items()
                if value.get("run_id") != run_id
            }
            return FakeResult(None)
        if compact.startswith("MERGE (n:StrategyOSNode:"):
            node_key = params["node_key"]
            self.nodes[node_key] = dict(params["properties"])
            return FakeResult(None)
        if (
            compact.startswith("MATCH (source:StrategyOSNode")
            and "MERGE (source)-[r:" in compact
        ):
            source = params["source_node_key"]
            target = params["target_node_key"]
            label = params["original_label"]
            self.edges[(source, target, label)] = dict(params["properties"])
            return FakeResult(None)
        if compact.startswith(
            "MATCH (n:StrategyOSNode {run_id: $run_id}) RETURN count(n) AS node_count"
        ):
            run_id = params["run_id"]
            count = sum(
                1 for node in self.nodes.values() if node.get("run_id") == run_id
            )
            return FakeResult({"node_count": count})
        if compact.startswith(
            "MATCH (:StrategyOSNode {run_id: $run_id})-[r]->(:StrategyOSNode {run_id: $run_id}) RETURN count(r) AS edge_count"
        ):
            run_id = params["run_id"]
            count = sum(
                1 for edge in self.edges.values() if edge.get("run_id") == run_id
            )
            return FakeResult({"edge_count": count})
        if compact.startswith(
            "MATCH (source:StrategyOSNode:Finding {run_id: $run_id})-[r]->(target:StrategyOSNode:Vendor {run_id: $run_id})"
        ):
            run_id = params["run_id"]
            for (source, target, _label), edge in self.edges.items():
                if edge.get("run_id") != run_id:
                    continue
                if not source.startswith("Finding:") or not target.startswith(
                    "Vendor:"
                ):
                    continue
                return FakeResult(
                    {
                        "source_node_key": source,
                        "relationship_type": "INVOLVES_VENDOR",
                        "target_node_key": target,
                        "original_label": edge.get("original_label"),
                    }
                )
            return FakeResult(None)
        raise AssertionError(f"Unexpected query: {compact}")


class FakeDriver:
    def __init__(self):
        self.session_instance = FakeSession()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def session(self):
        return self.session_instance


def test_sync_knowledge_graph_loads_nodes_edges_and_exposes_sample_query(
    tmp_path, monkeypatch
):
    graph_path = tmp_path / "StrategyOS Knowledge Graph.json"
    graph_path.write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "id": "Finding:F-001",
                        "label": "Finding",
                        "properties": {"finding_id": "F-001"},
                    },
                    {
                        "id": "Vendor:V-001",
                        "label": "Vendor",
                        "properties": {"vendor_id": "V-001"},
                    },
                ],
                "edges": [
                    {
                        "source": "Finding:F-001",
                        "target": "Vendor:V-001",
                        "label": "INVOLVES_VENDOR",
                        "properties": {"confidence": "HIGH"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    fake_driver = FakeDriver()
    monkeypatch.setattr(neo4j_store, "_graph_driver", lambda: fake_driver)
    monkeypatch.setattr(
        neo4j_store,
        "CONFIG",
        SimpleNamespace(neo4j_uri="bolt://neo4j:7687"),
    )

    sync = neo4j_store.sync_knowledge_graph(
        run_id="run-123",
        tenant_slug="local-poc",
        knowledge_graph_path=graph_path,
        authoritative_status={
            "status": "persisted",
            "data_management": {"kg_nodes": 2, "kg_edges": 1},
        },
    )

    assert sync["status"] == "synced"
    assert sync["source_counts"] == {"nodes": 2, "edges": 1}
    assert sync["node_count"] == 2
    assert sync["edge_count"] == 1
    assert sync["projection_guardrails"]["status"] == "ok"
    assert sync["projection_guardrails"]["counts_match"] is True
    assert sync["sample_relation"] == {
        "source_node_key": "Finding:F-001",
        "relationship_type": "INVOLVES_VENDOR",
        "target_node_key": "Vendor:V-001",
        "original_label": "INVOLVES_VENDOR",
    }
    assert any(
        "CREATE CONSTRAINT strategyos_node_identity" in statement
        for statement in fake_driver.session_instance.statements
    )


def test_sync_knowledge_graph_blocks_when_postgres_source_of_truth_is_missing(
    tmp_path, monkeypatch
):
    graph_path = tmp_path / "StrategyOS Knowledge Graph.json"
    graph_path.write_text(json.dumps({"nodes": [{"id": "n1"}], "edges": []}), encoding="utf-8")
    fake_driver = FakeDriver()
    monkeypatch.setattr(neo4j_store, "_graph_driver", lambda: fake_driver)
    monkeypatch.setattr(
        neo4j_store,
        "CONFIG",
        SimpleNamespace(neo4j_uri="bolt://neo4j:7687"),
    )

    sync = neo4j_store.sync_knowledge_graph(
        run_id="run-123",
        tenant_slug="local-poc",
        knowledge_graph_path=graph_path,
        authoritative_status={"status": "skipped"},
    )

    assert sync["status"] == "blocked"
    assert "persisted Postgres source-of-truth record" in sync["reason"]
    assert sync["projection_guardrails"]["status"] == "blocked"
    assert fake_driver.session_instance.statements == []


def test_graph_status_fails_when_neo4j_outpaces_authoritative_sources(monkeypatch, tmp_path):
    graph_path = tmp_path / "StrategyOS Knowledge Graph.json"
    graph_path.write_text(json.dumps({"nodes": [{"id": "n1"}], "edges": []}), encoding="utf-8")
    fake_driver = FakeDriver()
    fake_driver.session_instance.nodes = {"n1": {"run_id": "run-123"}}
    monkeypatch.setattr(neo4j_store, "_graph_driver", lambda: fake_driver)
    monkeypatch.setattr(
        neo4j_store,
        "CONFIG",
        SimpleNamespace(neo4j_uri="bolt://neo4j:7687"),
    )
    monkeypatch.setattr(
        neo4j_store,
        "data_management_status",
        lambda run_id: {
            "status": "ready",
            "run_id": run_id,
            "counts": {"kg_nodes": 0, "kg_edges": 0},
            "artifacts": {"knowledge_graph": str(graph_path)},
        },
    )

    payload = neo4j_store.graph_status_for_run("run-123")

    assert payload["status"] == "failed"
    assert "counts diverge" in payload["reason"]
    assert payload["projection_guardrails"]["status"] == "blocked"


def test_graph_status_reports_empty_projection_without_error(monkeypatch, tmp_path):
    graph_path = tmp_path / "StrategyOS Knowledge Graph.json"
    graph_path.write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")
    fake_driver = FakeDriver()
    monkeypatch.setattr(neo4j_store, "_graph_driver", lambda: fake_driver)
    monkeypatch.setattr(
        neo4j_store,
        "CONFIG",
        SimpleNamespace(neo4j_uri="bolt://neo4j:7687"),
    )
    monkeypatch.setattr(
        neo4j_store,
        "data_management_status",
        lambda run_id: {
            "status": "ready",
            "run_id": run_id,
            "counts": {"kg_nodes": 0, "kg_edges": 0},
            "artifacts": {"knowledge_graph": str(graph_path)},
        },
    )

    payload = neo4j_store.graph_status_for_run("run-empty")

    assert payload["status"] == "empty"
    assert "No graph nodes" in payload["reason"]
    assert payload["projection_guardrails"]["status"] == "ok"


def test_data_status_includes_neo4j_graph_summary(monkeypatch):
    monkeypatch.setattr(
        api_module,
        "data_management_status",
        lambda: {
            "status": "ready",
            "run_id": "run-123",
            "counts": {"kg_nodes": 2, "kg_edges": 1},
        },
    )
    monkeypatch.setattr(
        api_module,
        "graph_status_for_run",
        lambda run_id: {
            "status": "ready",
            "run_id": run_id,
            "node_count": 2,
            "edge_count": 1,
            "sample_relation": {
                "source_node_key": "Finding:F-001",
                "relationship_type": "INVOLVES_VENDOR",
                "target_node_key": "Vendor:V-001",
                "original_label": "INVOLVES_VENDOR",
            },
        },
    )

    payload = api_module.data_status()

    assert payload["neo4j"]["status"] == "ready"
    assert payload["neo4j"]["node_count"] == 2
    assert payload["neo4j"]["sample_relation"]["relationship_type"] == "INVOLVES_VENDOR"


def test_data_status_includes_qdrant_vector_summary(monkeypatch):
    monkeypatch.setattr(
        api_module,
        "data_management_status",
        lambda: {
            "status": "ready",
            "run_id": "run-123",
            "counts": {"findings": 2},
        },
    )
    monkeypatch.setattr(
        api_module,
        "graph_status_for_run",
        lambda run_id: {"status": "ready", "run_id": run_id},
    )
    monkeypatch.setattr(
        api_module,
        "vector_status_for_run",
        lambda run_id: {
            "status": "ready",
            "run_id": run_id,
            "point_count": 2,
            "sample_record": {"finding_id": "F-002", "title": "Duplicate payment"},
        },
    )

    payload = api_module.data_status()

    assert payload["qdrant"]["status"] == "ready"
    assert payload["qdrant"]["point_count"] == 2
    assert payload["qdrant"]["sample_record"]["finding_id"] == "F-002"
