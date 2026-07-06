from __future__ import annotations

import math
from types import SimpleNamespace

import strategyos_mvp.vector_store as vector_store
from strategyos_mvp.models import Citation, Finding


def _sample_finding(
    finding_id: str, title: str, pattern_type: str, vendor_name: str
) -> Finding:
    return Finding(
        finding_id=finding_id,
        title=title,
        pattern_type=pattern_type,
        vendor_id=f"V-{finding_id}",
        vendor_name=vendor_name,
        leakage_sar=100.0,
        recoverable_sar=80.0,
        recoverable_usd=21.33,
        confidence="HIGH",
        classification="test",
        rationale=title,
        remediation="Review the control and recover the amount.",
        status="locked",
    )


def _matches_filter(point, filter_payload):
    for clause in filter_payload.get("must", []):
        value = point["payload"].get(clause["key"])
        match = clause.get("match") or {}
        if "value" in match and value != match["value"]:
            return False
        if "any" in match and value not in match["any"]:
            return False
    return True


def test_sync_and_search_vectors_for_a_run(monkeypatch, tmp_path):
    state = {"collections": set(), "points": []}

    def fake_request(method: str, path: str, payload=None):
        if method == "GET" and path == "/":
            return {"version": "1.9.5"}
        if method == "GET" and path.startswith("/collections/"):
            name = path.split("/")[2]
            if name not in state["collections"]:
                raise RuntimeError(
                    f"Qdrant request failed (404) for /collections/{name}: missing"
                )
            return {"result": {"status": "green"}}
        if method == "GET" and path == "/collections":
            return {
                "result": {
                    "collections": [{"name": name} for name in state["collections"]]
                }
            }
        if (
            method == "PUT"
            and path
            == f"/collections/{vector_store.COLLECTION_NAME}/points?wait=true"
        ):
            for point in payload["points"]:
                state["points"] = [p for p in state["points"] if p["id"] != point["id"]]
                state["points"].append(point)
            return {"result": {"status": "acknowledged"}}
        if method == "PUT" and path.startswith("/collections/") and path.endswith("/index"):
            return {"result": True}
        if method == "PUT" and path.startswith("/collections/"):
            name = path.split("/")[2]
            state["collections"].add(name)
            return {"result": True}
        if method == "POST" and path.endswith("/points/count"):
            run_id = payload["filter"]["must"][0]["match"]["value"]
            count = sum(
                1
                for point in state["points"]
                if point["payload"]["run_id"] == run_id
                and _matches_filter(point, payload["filter"])
            )
            return {"result": {"count": count}}
        if method == "POST" and path.endswith("/points/scroll"):
            run_id = payload["filter"]["must"][0]["match"]["value"]
            points = [
                point
                for point in state["points"]
                if point["payload"]["run_id"] == run_id
                and _matches_filter(point, payload["filter"])
            ]
            return {"result": {"points": points[: payload.get("limit", 1)]}}
        raise AssertionError(f"Unexpected request: {method} {path}")

    monkeypatch.setattr(vector_store, "_qdrant_request", fake_request)
    monkeypatch.setattr(
        vector_store,
        "CONFIG",
        SimpleNamespace(qdrant_url="http://qdrant:6333"),
    )

    kg_path = tmp_path / "StrategyOS Knowledge Graph.json"
    kg_path.write_text("{}", encoding="utf-8")
    findings = [
        _sample_finding(
            "F-001",
            "Auto-renewal escalation at Gulf Logistics Services Co",
            "auto_renewal_escalation",
            "Gulf Logistics Services Co",
        ),
        _sample_finding(
            "F-002",
            "Duplicate payment for invoice INV-2026-0341",
            "duplicate_payment",
            "Premier Packaging LLC",
        ),
    ]
    findings[1].citations.append(
        Citation(
            source_path="uploads/ap_ledger.csv",
            locator="row 341",
            excerpt="Invoice INV-2026-0341 was paid twice to Premier Packaging LLC.",
            source_hash="sha256:test",
        )
    )

    sync = vector_store.sync_findings_vector_store(
        run_id="run-123",
        tenant_slug="local-poc",
        findings=findings,
        knowledge_graph_path=kg_path,
    )
    search = vector_store.search_run_vectors(
        "run-123", "INV-2026-0341", limit=1
    )
    filtered = vector_store.search_run_vectors(
        "run-123", "invoice", limit=5, point_type="citation"
    )
    status = vector_store.vector_status_for_run("run-123")

    assert sync["status"] == "synced"
    assert sync["point_count"] == 4
    assert sync["point_types"] == {"finding": 2, "citation": 1, "evidence_chunk": 1}
    assert search["status"] == "ready"
    assert search["mode"] == "lexical_keyword"
    assert search["embedding_backend"] == "hash_fallback"
    assert search["results"][0]["finding_id"] == "F-002"
    assert search["results"][0]["ranking"]["mode"] == "lexical_keyword"
    assert search["results"][0]["open_evidence"]["href"].startswith("/data/evidence-preview?")
    assert filtered["filters"] == {"point_type": ["citation"]}
    assert {item["result_type"] for item in filtered["results"]} == {"citation"}
    assert status["status"] == "ready"
    assert status["sample_record"]["source"].endswith("StrategyOS Knowledge Graph.json")


def test_empty_vector_status_is_not_reported_as_missing(monkeypatch, tmp_path):
    state = {"collections": set()}

    def fake_request(method: str, path: str, payload=None):
        if method == "GET" and path.startswith("/collections/"):
            name = path.split("/")[2]
            if name not in state["collections"]:
                raise RuntimeError(
                    f"Qdrant request failed (404) for /collections/{name}: missing"
                )
            return {"result": {"status": "green"}}
        if method == "PUT" and path.startswith("/collections/") and path.endswith("/index"):
            return {"result": True}
        if method == "PUT" and path.startswith("/collections/"):
            state["collections"].add(path.split("/")[2])
            return {"result": True}
        if method == "POST" and path.endswith("/points/count"):
            return {"result": {"count": 0}}
        raise AssertionError(f"Unexpected request: {method} {path}")

    monkeypatch.setattr(vector_store, "_qdrant_request", fake_request)
    monkeypatch.setattr(
        vector_store,
        "CONFIG",
        SimpleNamespace(qdrant_url="http://qdrant:6333"),
    )

    sync = vector_store.sync_findings_vector_store(
        run_id="run-empty",
        tenant_slug="local-poc",
        findings=[],
        knowledge_graph_path=tmp_path / "kg.json",
    )
    status = vector_store.vector_status_for_run("run-empty")

    assert sync["status"] == "empty"
    assert sync["point_count"] == 0
    assert status["status"] == "empty"
    assert status["point_count"] == 0


def test_embed_text_returns_normalized_vector():
    vector = vector_store._embed_text("duplicate payment invoice")

    magnitude = math.sqrt(sum(value * value for value in vector))
    assert len(vector) == vector_store.VECTOR_SIZE
    assert round(magnitude, 6) == 1.0


def test_check_qdrant_ready_reports_truthful_keyword_mode(monkeypatch):
    monkeypatch.setattr(
        vector_store,
        "CONFIG",
        SimpleNamespace(qdrant_url="http://qdrant:6333"),
    )
    monkeypatch.setattr(
        vector_store,
        "_qdrant_request",
        lambda method, path, payload=None: {"result": {"collections": []}} if path == "/collections" else {"version": "1.13.0"},
    )
    monkeypatch.setattr(vector_store, "_qdrant_version", lambda: "1.13.0")

    payload = vector_store.check_qdrant_ready()

    assert payload["embedding_backend"] == "hash_fallback"
    assert payload["native_hybrid_supported"] is False
    assert payload["hybrid_mode"] == "lexical_keyword"
