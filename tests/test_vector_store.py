from __future__ import annotations

import math
from types import SimpleNamespace

import strategyos_mvp.vector_store as vector_store
from strategyos_mvp.models import Finding


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


def test_sync_and_search_vectors_for_a_run(monkeypatch, tmp_path):
    state = {"collections": set(), "points": []}

    def fake_request(method: str, path: str, payload=None):
        if method == "GET" and path == "/collections/strategyos_findings":
            if "strategyos_findings" not in state["collections"]:
                raise RuntimeError(
                    "Qdrant request failed (404) for /collections/strategyos_findings: missing"
                )
            return {"result": {"status": "green"}}
        if method == "GET" and path == "/collections":
            return {
                "result": {
                    "collections": [{"name": name} for name in state["collections"]]
                }
            }
        if method == "PUT" and path == "/collections/strategyos_findings":
            state["collections"].add("strategyos_findings")
            return {"result": True}
        if (
            method == "PUT"
            and path == "/collections/strategyos_findings/points?wait=true"
        ):
            for point in payload["points"]:
                state["points"] = [p for p in state["points"] if p["id"] != point["id"]]
                state["points"].append(point)
            return {"result": {"status": "acknowledged"}}
        if method == "POST" and path == "/collections/strategyos_findings/points/count":
            run_id = payload["filter"]["must"][0]["match"]["value"]
            count = sum(
                1 for point in state["points"] if point["payload"]["run_id"] == run_id
            )
            return {"result": {"count": count}}
        if (
            method == "POST"
            and path == "/collections/strategyos_findings/points/scroll"
        ):
            run_id = payload["filter"]["must"][0]["match"]["value"]
            points = [
                point
                for point in state["points"]
                if point["payload"]["run_id"] == run_id
            ]
            return {"result": {"points": points[: payload.get("limit", 1)]}}
        if (
            method == "POST"
            and path == "/collections/strategyos_findings/points/search"
        ):
            run_id = payload["filter"]["must"][0]["match"]["value"]
            query_vector = payload["vector"]
            matches = []
            for point in state["points"]:
                if point["payload"]["run_id"] != run_id:
                    continue
                score = sum(
                    a * b for a, b in zip(query_vector, point["vector"], strict=False)
                )
                matches.append({"payload": point["payload"], "score": score})
            matches.sort(key=lambda item: item["score"], reverse=True)
            return {"result": matches[: payload.get("limit", 5)]}
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

    sync = vector_store.sync_findings_vector_store(
        run_id="run-123",
        tenant_slug="local-poc",
        findings=findings,
        knowledge_graph_path=kg_path,
    )
    search = vector_store.search_run_vectors(
        "run-123", "duplicate payment invoice", limit=1
    )
    status = vector_store.vector_status_for_run("run-123")

    assert sync["status"] == "synced"
    assert sync["point_count"] == 2
    assert search["status"] == "ready"
    assert search["results"][0]["finding_id"] == "F-002"
    assert status["status"] == "ready"
    assert status["sample_record"]["source"].endswith("StrategyOS Knowledge Graph.json")


def test_embed_text_returns_normalized_vector():
    vector = vector_store._embed_text("duplicate payment invoice")

    magnitude = math.sqrt(sum(value * value for value in vector))
    assert len(vector) == vector_store.VECTOR_SIZE
    assert round(magnitude, 6) == 1.0
