from __future__ import annotations

from strategyos_mvp.executive_presentation import build_executive_presentation
from strategyos_mvp.executive_read_model import build_executive_read_model
from strategyos_mvp import api as api_module
from strategyos_mvp import state_store as state_store_module


def _strings(value):
    if isinstance(value, dict):
        out = []
        for child in value.values():
            out.extend(_strings(child))
        return out
    if isinstance(value, list):
        out = []
        for child in value:
            out.extend(_strings(child))
        return out
    if isinstance(value, str):
        return [value]
    return []


def test_mizan_style_presentation_uses_database_claims_only():
    read_model = build_executive_read_model(
        {
            "run_id": "latest-public",
            "_backing_run_id": "2bb5fdeb-ed53-4953-9f5a-55b2959c5a43",
            "created_at": "2026-07-12T09:00:00+00:00",
            "approval_status": "pending",
            "current_stage": "awaiting_review",
        },
        [
            {
                "finding_id": "F-001",
                "title": "Duplicate payment",
                "pattern_type": "duplicate_payment",
                "recoverable_sar": 177188.0,
                "citation_count": 3,
                "challenged": True,
            },
            {
                "finding_id": "F-002",
                "title": "Dormant supplier credit",
                "pattern_type": "dormant_credit_balance",
                "recoverable_sar": 128000.0,
                "citation_count": 2,
                "challenged": False,
            },
        ],
        {"resolved_count": 4},
        {"report_count": 1},
        {},
        truth_source="database",
    )
    presentation = build_executive_presentation(read_model)
    all_text = "\n".join(_strings(presentation))

    assert presentation["mode"] == "live"
    assert presentation["source"] == "database"
    assert presentation["run_id"] == "2bb5fdeb-ed53-4953-9f5a-55b2959c5a43"
    assert [card["label"] for card in presentation["driver_grid"]] == [
        "Revenue",
        "EBITDA margin",
        "Operating cost",
        "Cash vs floor",
    ]
    assert presentation["driver_grid"][0]["metric"] == "Not available"
    assert presentation["driver_grid"][0]["availability"] == "unavailable"
    assert "No value has been estimated" in presentation["driver_grid"][0]["detail"]
    assert presentation["hero"]["label"] == "CEO finance baseline is not yet connected"
    assert presentation["sections"]["developments"]["items"] == []
    assert presentation["sections"]["week_ahead"]["items"] == []
    assert presentation["provenance_summary"]["all_claims_validated"] is True
    assert "Mizan Group" not in all_text
    assert "SAR 8.6M" not in all_text
    assert "NUPCO" not in all_text
    assert "GLP-1" not in all_text


def test_read_model_marks_missing_data_without_demo_fallback():
    read_model = build_executive_read_model(
        None, [], None, None, None, truth_source="database"
    )
    presentation = build_executive_presentation(read_model)

    assert presentation["data_status"] == "missing"
    assert presentation["run_id"] is None
    assert presentation["hero"]["label"] == "Board readiness is unavailable"
    assert presentation["sections"]["developments"]["items"] == []
    assert presentation["sections"]["week_ahead"]["items"] == []


def test_presentation_keeps_all_cases_in_navigation_index_but_renders_three():
    rows = [
        {
            "finding_id": f"F-{index:03d}",
            "title": f"Case {index}",
            "pattern_type": "duplicate_payment",
            "recoverable_sar": 1000 - index,
            "citation_count": index,
            "challenged": False,
        }
        for index in range(1, 51)
    ]
    read_model = build_executive_read_model(
        {
            "run_id": "2bb5fdeb-ed53-4953-9f5a-55b2959c5a43",
            "created_at": "2026-07-12T09:00:00+00:00",
        },
        rows,
        {"resolved_count": 100},
        {"report_count": 1},
        {},
        truth_source="database",
    )

    presentation = build_executive_presentation(read_model)

    assert len(presentation["sections"]["findings"]["items"]) == 3
    assert len(presentation["sections"]["findings"]["case_index"]) == 50
    assert presentation["sections"]["findings"]["case_index"][49]["finding_id"] == "F-050"


def test_unknown_public_citation_resolution_stays_unknown():
    read_model = build_executive_read_model(
        {
            "run_id": "latest-public",
            "_backing_run_id": "2bb5fdeb-ed53-4953-9f5a-55b2959c5a43",
        },
        [{"finding_id": "F-001", "recoverable_sar": 10, "citation_count": 2}],
        {"resolved_count": None},
        {"report_count": 1},
        {},
        truth_source="database",
    )

    presentation = build_executive_presentation(read_model)
    citation_claim = read_model["metrics"]["citation_resolution"]

    assert citation_claim["value"] == {"resolved": None, "total": 2}
    assert citation_claim["provenance"]["complete"] is False
    assert presentation["driver_grid"][2]["metric"] == "Not available"
    assert presentation["hero"]["readiness_operands"]["citation_resolved"] is None


def test_citation_ratio_uses_audit_total_and_rejects_impossible_counts():
    read_model = build_executive_read_model(
        {"run_id": "local-run"},
        [{"finding_id": "F-001", "recoverable_sar": 10, "citation_count": 2}],
        {"citation_count": 5, "resolved_count": 5},
        {"report_count": 1},
        {},
    )
    presentation = build_executive_presentation(read_model)

    assert read_model["metrics"]["citation_resolution"]["value"] == {
        "resolved": 5,
        "total": 5,
    }
    assert presentation["driver_grid"][2]["metric"] == "Not available"
    assert presentation["hero"]["score_note"] == "current posture"

    impossible = build_executive_read_model(
        {"run_id": "local-run"},
        [{"finding_id": "F-001", "recoverable_sar": 10, "citation_count": 2}],
        {"citation_count": 5, "resolved_count": 6},
        {"report_count": 1},
        {},
    )
    impossible_presentation = build_executive_presentation(impossible)
    assert impossible["metrics"]["citation_resolution"]["provenance"]["complete"] is False
    assert impossible_presentation["driver_grid"][2]["metric"] == "Not available"


def test_ceo_kpi_contract_uses_only_authoritative_deterministic_finance_inputs():
    read_model = build_executive_read_model(
        {
            "run_id": "oracle-run",
            "created_at": "2026-07-12T09:00:00+00:00",
            "oracle_kpi": {
                "derived_from": "deterministic_oracle_kpi_engine",
                "authoritative": True,
                "reporting_period_key": "2026-06",
                "components": {
                    "revenue_actual": "1200000",
                    "revenue_plan": "1000000",
                    "ebitda_actual": "240000",
                    "ebitda_plan": "180000",
                    "operating_cost_actual": "630000",
                    "operating_cost_plan": "600000",
                    "cash_balance": "500000",
                    "board_floor": "400000",
                },
            },
        },
        [],
        {},
        {"report_count": 0},
        {},
    )

    cards = build_executive_presentation(read_model)["driver_grid"]

    assert [card["key"] for card in cards] == [
        "revenue",
        "ebitda_margin",
        "operating_cost",
        "cash_vs_floor",
    ]
    assert cards[0]["metric"] == "SAR 1.2M"
    assert cards[0]["pct"] == 120.0
    assert cards[1]["metric"] == "20.0%"
    assert cards[1]["comparison"] == "+200 bps vs plan"
    assert cards[2]["pct"] == 105.0
    assert cards[3]["comparison"] == "SAR 100K above floor"
    assert all(card["availability"] == "verified" for card in cards)
    assert all(
        card["trend"] == {"actual": [], "plan": [], "labels": [], "has_plan_series": False, "unit": ""}
        for card in cards
    )
    assert cards[1]["executive_brief"]["calculation"]["steps"][1] == {
        "label": "Less cost of goods sold",
        "value": "Not supplied",
    }


def test_ceo_kpi_contract_refuses_untrusted_oracle_shaped_payload():
    read_model = build_executive_read_model(
        {
            "run_id": "untrusted-run",
            "oracle_kpi": {
                "derived_from": "spreadsheet",
                "authoritative": False,
                "components": {"revenue_actual": "999999999"},
            },
        },
        [],
        {},
        {},
        {},
    )

    card = build_executive_presentation(read_model)["driver_grid"][0]
    assert card["metric"] == "Not available"
    assert card["availability"] == "unavailable"


def test_api_prefers_database_snapshot_and_labels_artifact_fallback(monkeypatch):
    snapshot = {
        "status": "ok",
        "summary": {
            "run_id": "2bb5fdeb-ed53-4953-9f5a-55b2959c5a43",
            "created_at": "2026-07-12T09:00:00+00:00",
        },
        "findings": [
            {
                "finding_id": "F-DB",
                "title": "Database case",
                "recoverable_sar": 25,
                "citation_count": 1,
            }
        ],
        "audit_summary": {"resolved_count": 1},
        "artifacts": {},
        "agent_events": [],
    }
    monkeypatch.setattr(
        api_module.state_store,
        "executive_snapshot_for_run",
        lambda _run_id: snapshot,
    )

    database_model = api_module._executive_read_model_from_available_truth(
        {"run_id": "2bb5fdeb-ed53-4953-9f5a-55b2959c5a43"},
        [{"finding_id": "F-FILE", "recoverable_sar": 999}],
        {"resolved_count": 0},
        {"report_count": 3},
        {},
        public_safe=False,
    )

    assert database_model["source"] == "database"
    assert database_model["findings"][0]["finding_id"]["value"] == "F-DB"

    monkeypatch.setattr(
        api_module.state_store,
        "executive_snapshot_for_run",
        lambda _run_id: {"status": "skipped", "reason": "DATABASE_URL is not configured."},
    )
    artifact_model = api_module._executive_read_model_from_available_truth(
        {"run_id": "local-run"},
        [{"finding_id": "F-FILE", "recoverable_sar": 999}],
        {"resolved_count": 0},
        {"report_count": 3},
        {},
        public_safe=False,
    )

    assert artifact_model["source"] == "governed_artifacts"
    assert artifact_model["findings"][0]["finding_id"]["value"] == "F-FILE"
    assert "DATABASE_URL is not configured" in artifact_model["status_reason"]


def test_database_executive_snapshot_reads_relational_truth(monkeypatch):
    run_id = "2bb5fdeb-ed53-4953-9f5a-55b2959c5a43"

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args):
            return None

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        state_store_module,
        "database_connection",
        lambda: (FakeConnection(), None),
    )
    monkeypatch.setattr(state_store_module, "ensure_data_schema", lambda _conn: None)
    monkeypatch.setattr(
        state_store_module,
        "fetchone_dict",
        lambda _cur: {
            "id": run_id,
            "created_at": "2026-07-12T09:00:00+00:00",
            "finding_count": 1,
            "locked_finding_count": 1,
            "total_recoverable_sar": 25,
            "status": "awaiting_review",
            "current_stage": "awaiting_review",
            "requires_human_review": True,
            "summary_json": {"run_id": "stale-id"},
            "latest_approval_decision": "approved",
        },
    )
    result_sets = iter(
        [
            [
                {
                    "finding_id": "F-DB",
                    "pattern_type": "duplicate_payment",
                    "status": "locked",
                    "confidence": "HIGH",
                    "recoverable_sar": 25,
                    "leakage_sar": 25,
                    "finding_json": {"title": "Database case"},
                    "citation_count": 2,
                    "resolved_citation_count": 1,
                    "challenged": True,
                }
            ],
            [{"artifact_name": "summary", "local_path": "/tmp/summary.pdf"}],
            [{"actor": "Auditor", "action": "challenge", "finding_id": "F-DB"}],
        ]
    )
    monkeypatch.setattr(
        state_store_module,
        "fetchall_dicts",
        lambda _cur: next(result_sets),
    )

    snapshot = state_store_module.executive_snapshot_for_run(run_id)

    assert snapshot["status"] == "ok"
    assert snapshot["summary"]["run_id"] == run_id
    assert snapshot["summary"]["approval_status"] == "approved"
    assert snapshot["findings"][0]["title"] == "Database case"
    assert snapshot["audit_summary"]["citation_count"] == 2
    assert snapshot["audit_summary"]["resolved_count"] == 1
    assert snapshot["artifacts"] == {"summary": "/tmp/summary.pdf"}


def test_executive_js_live_database_mode_does_not_fallback_to_synthetic_rails():
    from pathlib import Path

    js_path = Path(__file__).resolve().parents[1] / "strategyos_mvp" / "static" / "executive.js"
    js = js_path.read_text(encoding="utf-8")

    assert 'diagnostics.mode === "live" && ["database", "governed_artifacts"]' in js
    assert "liveGovernedMode\n      ? safeArray(developmentsSection.items)" in js
    assert "liveGovernedMode\n      ? safeArray(weekSection.items)" in js
    assert "developmentsPanel.hidden = false" in js
    assert "Signals to watch" in js
    assert "No case-level decision is escalated to the CEO" in js
    assert "No governed calendar is available for this reporting period" in js
    assert "findingsSection.case_index" in js
    assert "state.selectedFindingId = targetId" in js
    assert "truthSourceBadge" not in js
    assert '"Business view ready"' in js
