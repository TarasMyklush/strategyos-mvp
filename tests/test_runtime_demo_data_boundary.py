"""Prevent illustrative executive claims from returning to runtime surfaces."""

from __future__ import annotations

from pathlib import Path


RUNTIME_SURFACE_FILES = (
    "strategyos_mvp/executive_design.py",
    "strategyos_mvp/api.py",
    "strategyos_mvp/llm_qa.py",
    "strategyos_mvp/scenario_parser.py",
    "strategyos_mvp/static/executive.js",
)

FORBIDDEN_STORY_MARKERS = (
    "nupco",
    "tamween",
    "glp-1",
    "sar 8.6m",
    "sar 1.2m",
    "60% eur",
    "recovered sar 8.6m",
)


def test_executive_runtime_contains_no_illustrative_storyline() -> None:
    root = Path(__file__).resolve().parents[1]
    surfaced = "\n".join((root / relative).read_text(encoding="utf-8").lower() for relative in RUNTIME_SURFACE_FILES)
    assert all(marker not in surfaced for marker in FORBIDDEN_STORY_MARKERS)


def test_illustrative_fixture_is_test_only() -> None:
    root = Path(__file__).resolve().parents[1]
    fixture = root / "tests/fixtures/executive_demo_packet.py"
    assert fixture.exists()
    assert "is_illustrative" in fixture.read_text(encoding="utf-8")


def test_executive_runtime_has_no_curated_external_editorial_surface() -> None:
    root = Path(__file__).resolve().parents[1]
    js = (root / "strategyos_mvp/static/executive.js").read_text(encoding="utf-8").lower()
    css = (root / "strategyos_mvp/static/executive.css").read_text(encoding="utf-8").lower()
    assert "leaders' corner" not in js
    assert "youtube" not in js
    assert "youtube" not in css
    for relative in (
        "deploy/caddy/Caddyfile",
        "deploy/caddy/Caddyfile.branch",
        "deploy/caddy/Caddyfile.proxy-oidc",
    ):
        caddy = (root / relative).read_text(encoding="utf-8").lower()
        assert "youtube" not in caddy
        assert "frame-src 'none'" in caddy
