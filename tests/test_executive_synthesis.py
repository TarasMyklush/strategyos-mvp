from __future__ import annotations

import strategyos_mvp.executive_synthesis as synthesis


def _payload() -> dict:
    return {
        "plan_health": {
            "commitments": [
                {
                    "kpi_id": "revenue",
                    "name": "Revenue",
                    "actual": 84,
                    "checkpoint": 100,
                    "unit": "%",
                    "status_vs_path": "behind path",
                }
            ]
        },
        "initiative_drifts": [
            {
                "initiative_id": "INIT-42",
                "title": "Channel recovery",
                "kpi_link": "revenue",
                "status": "at risk",
                "note": "Two distributor launches moved beyond the approved window",
            }
        ],
        "milestone_drifts": [],
        "achievements": [],
        "assistant_threads": {
            "threads": [
                {
                    "thread_id": "a2a-1",
                    "participants": ["Hermes", "Atlas"],
                    "topic": "Revenue recovery",
                    "status": "complete",
                    "turns": [
                        {"text": "Revenue is 16% below checkpoint."},
                        {"text": "Recover SAR 2.4M through INIT-42 by Friday."},
                    ],
                }
            ]
        },
    }


def test_refresh_synthesis_is_grounded_substantive_and_cached(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("STRATEGYOS_EXECUTIVE_SYNTHESIS_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(synthesis, "_provider_batch", lambda developments, threads: None)

    first = synthesis.synthesize_strategy_enrichment(_payload())
    second = synthesis.synthesize_strategy_enrichment(_payload())

    brief = first["development_briefs"][0]
    assert first["synthesis_cache"]["status"] == "miss"
    assert second["synthesis_cache"]["status"] == "hit"
    assert brief["what"] != brief["why"]
    assert "84%" in brief["what"] and "100%" in brief["what"]
    assert "INIT-42" in brief["why"]
    assert "Options:" in brief["rich_briefing"]
    thread = first["assistant_threads"]["threads"][0]
    assert thread["executive_summary"]
    assert "16%" in thread["key_figures"]
    assert "SAR 2.4M" in thread["key_figures"]


def test_ungrounded_provider_numbers_are_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("STRATEGYOS_EXECUTIVE_SYNTHESIS_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(
        synthesis,
        "_provider_batch",
        lambda developments, threads: {
            "development_briefs": [
                {"item_id": "revenue", "what": "Revenue reached 999%.", "why": "Because we guessed."}
            ]
        },
    )

    result = synthesis.synthesize_strategy_enrichment(_payload())
    brief = result["development_briefs"][0]
    assert brief["synthesized_by"] == "deterministic-correlation"
    assert "999" not in brief["what"]


def test_default_cache_uses_writable_workspace_root(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("STRATEGYOS_EXECUTIVE_SYNTHESIS_CACHE_DIR", raising=False)
    monkeypatch.setenv("STRATEGYOS_WORKSPACE_ROOT", str(tmp_path))
    assert synthesis._cache_root() == tmp_path / ".strategyos_mvp_data" / "executive_synthesis"
