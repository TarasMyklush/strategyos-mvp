from pathlib import Path
import shutil

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from strategyos_mvp import auth, demo_pack
from strategyos_mvp.demo_pack_api import router


def client(role="executive"):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[auth.authenticate_request] = lambda: {
        "tenant_id": "test-tenant", "subject": "test-user", "role": role,
        "authenticated": True, "auth_disabled": False,
    }
    return TestClient(app)


def test_configured_pack_runs_three_evidence_bound_stories_into_board_pages():
    pack = demo_pack.load_pack()
    catalog = demo_pack.build_catalog(pack)
    assert catalog["controls"] == {
        "mode": "synthetic", "persistence": "read_only", "authority_effect": "none",
        "sector_layer": "configuration_only",
    }
    assert len(catalog["stories"]) == 3
    assert len(catalog["catalog_digest"]) == 64
    for story in pack.stories:
        detail = demo_pack.story_detail(story.story_id, pack)
        assert detail["analysis"]["approval_status"] == "ratified"
        assert all(cell["plan_source"]["sha256"] for cell in detail["analysis"]["cells"])
        assert detail["board_pack"]["binding"]["composer_version"] == "board-pack.v3"
        assert detail["board_pack"]["binding"]["analysis_hash"] == detail["analysis"]["analysis_hash"]
        assert detail["board_pack"]["evidence"]
        assert any(any("\u0600" <= character <= "\u06ff" for character in line)
                   for page in detail["board_pack"]["pages"] for line in page["lines"])


def test_each_story_proves_its_intended_decision_pattern():
    rescue = demo_pack.story_detail("regional-client-rescue")
    assert rescue["analysis"]["rollups"][0]["status"] == "on_plan"
    assert {item["finding_type"] for item in rescue["analysis"]["findings"]} == {"offset", "concentration"}
    concentration = next(item for item in rescue["analysis"]["findings"] if item["finding_type"] == "concentration")
    assert concentration["member"] == "nupco"
    assert concentration["share_percent"] == "75.00"

    bridge = demo_pack.story_detail("price-volume-mix")
    mix_story = next(item for item in demo_pack.load_pack().stories if item.story_id == "price-volume-mix")
    assert mix_story.plan.derivation.engine_version == "history-adjusted-allocation.v1"
    assert mix_story.plan.derivation.historical_actual_digest
    effect = bridge["analysis"]["price_volume_mix"][0]
    assert effect["effects"] == {
        "volume": "60.00", "mix": "-30.00", "price": "3.00",
        "observed_variance": "33", "reconstructed_variance": "33.00",
    }
    assert effect["reconciles"] is True
    assert {"plan_price", "plan_volume", "actual_price", "actual_volume"} <= {
        item["side"] for item in bridge["board_pack"]["evidence"]}
    assert any("60.00" in line for page in bridge["board_pack"]["pages"] for line in page["lines"])

    constrained = demo_pack.story_detail("regional-credit-constraint")
    assert constrained["analysis"]["rollups"][0]["status"] == "behind"
    assert constrained["story"]["context_links"][0]["relationship"] == "constrained_by"


def test_tampered_demo_evidence_fails_closed(tmp_path):
    shutil.copytree(demo_pack.DEFAULT_ROOT, tmp_path / "pack")
    (tmp_path / "pack" / "evidence.csv").write_text("tampered", encoding="utf-8")
    pack = demo_pack.load_pack(tmp_path / "pack" / "pack.json")
    with pytest.raises(ValueError, match="Evidence hash differs"):
        demo_pack.story_detail(pack.stories[0].story_id, pack, source_root=tmp_path / "pack")


def test_sector_language_lives_only_in_pack_data():
    root = Path(demo_pack.__file__).parent
    core = (root / "demo_pack.py").read_text(encoding="utf-8").lower()
    api = (root / "demo_pack_api.py").read_text(encoding="utf-8").lower()
    html = (root / "static" / "plan.html").read_text(encoding="utf-8").lower()
    js = (root / "static" / "demo_pack.js").read_text(encoding="utf-8").lower()
    configured = demo_pack.DEFAULT_PACK.read_text(encoding="utf-8").lower()
    for term in ("healthcare", "pharma", "nupco", "oncology", "hospital"):
        assert term not in core + api + html + js
        assert term in configured


def test_authenticated_demo_api_supports_catalog_story_and_evidence_drilldown():
    with client() as api:
        catalog = api.get("/api/demo-packs/current")
        assert catalog.status_code == 200
        story_id = catalog.json()["stories"][0]["story_id"]
        story = api.get("/api/demo-packs/current/stories/" + story_id)
        assert story.status_code == 200
        evidence = story.json()["board_pack"]["evidence"][0]
        opened = api.get(evidence["path"])
        assert opened.status_code == 200
        assert opened.headers["x-kyvern-source-sha256"] == evidence["source"]["sha256"]
        bridge = api.get("/api/demo-packs/current/stories/price-volume-mix").json()
        bridge_input = next(item for item in bridge["board_pack"]["evidence"]
                            if item["side"] == "actual_price")
        assert api.get(bridge_input["path"]).status_code == 200
        assert api.get("/api/demo-packs/current/stories/missing").status_code == 404
    with client("bu") as api:
        assert api.get("/api/demo-packs/current").status_code == 403


def test_intent_surface_loads_configured_pack_without_sector_copy_in_core():
    root = Path(demo_pack.__file__).parent / "static"
    html = (root / "plan.html").read_text(encoding="utf-8")
    js = (root / "demo_pack.js").read_text(encoding="utf-8")
    assert 'id="demo-pack-panel"' in html
    assert 'src="/static/demo_pack.js"' in html
    assert "/api/demo-packs/current" in js
    assert "Bilingual board-pack preview" in html
    assert "Open governed story" in js
