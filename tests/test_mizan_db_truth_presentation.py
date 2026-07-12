from __future__ import annotations

from strategyos_mvp.executive_presentation import build_executive_presentation
from strategyos_mvp.executive_read_model import build_executive_read_model


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
    )
    presentation = build_executive_presentation(read_model)
    all_text = "\n".join(_strings(presentation))

    assert presentation["mode"] == "live"
    assert presentation["source"] == "database"
    assert presentation["run_id"] == "2bb5fdeb-ed53-4953-9f5a-55b2959c5a43"
    assert presentation["driver_grid"][0]["label"] == "Cash recovery opportunity"
    assert presentation["driver_grid"][0]["metric"] == "SAR 305K"
    assert presentation["sections"]["developments"]["items"] == []
    assert presentation["sections"]["week_ahead"]["items"] == []
    assert presentation["provenance_summary"]["all_claims_validated"] is True
    assert "Mizan Group" not in all_text
    assert "SAR 8.6M" not in all_text
    assert "NUPCO" not in all_text
    assert "GLP-1" not in all_text


def test_read_model_marks_missing_data_without_demo_fallback():
    read_model = build_executive_read_model(None, [], None, None, None)
    presentation = build_executive_presentation(read_model)

    assert presentation["data_status"] == "missing"
    assert presentation["run_id"] is None
    assert presentation["hero"]["label"] == "Board readiness is unavailable"
    assert presentation["sections"]["developments"]["items"] == []
    assert presentation["sections"]["week_ahead"]["items"] == []


def test_executive_js_live_database_mode_does_not_fallback_to_synthetic_rails():
    from pathlib import Path

    js_path = Path(__file__).resolve().parents[1] / "strategyos_mvp" / "static" / "executive.js"
    js = js_path.read_text(encoding="utf-8")

    assert 'diagnostics.mode === "live" && diagnostics.source === "database"' in js
    assert "liveDatabaseMode\n      ? safeArray(developmentsSection.items)" in js
    assert "liveDatabaseMode\n      ? safeArray(weekSection.items)" in js
    assert "developmentsPanel.hidden = liveDatabaseMode && !developments.length" in js
    assert "weekPanel.hidden = liveDatabaseMode && !weekAhead.length" in js
