"""Typed, sector-neutral configured decision stories for product demonstrations.

The runtime understands evidence-bound plans, actuals, relationships and board
templates.  Client and sector language belongs to the selected JSON pack only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode

from pydantic import Field, model_validator

from .board_pack import PackRequest, PackTemplate, compose_snapshot
from .dimensional_plan import Actuals, Contract, Name, Plan, evaluate, verify_source


class DemoControls(Contract):
    mode: Literal["synthetic"] = "synthetic"
    persistence: Literal["read_only"] = "read_only"
    authority_effect: Literal["none"] = "none"
    sector_layer: Literal["configuration_only"] = "configuration_only"


class ContextLink(Contract):
    from_cell_id: Name
    relationship: Name
    to_reference: Name
    label: str = Field(min_length=8, max_length=300)


class DemoStory(Contract):
    story_id: Name
    title: Name
    question: str = Field(min_length=20, max_length=500)
    decision_prompt: str = Field(min_length=20, max_length=500)
    plan: Plan
    actuals: Actuals
    board_template: PackTemplate
    context_links: list[ContextLink] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def aligned_snapshots(self):
        if self.plan.company_id != self.actuals.company_id or self.plan.period != self.actuals.period:
            raise ValueError("A demo story requires aligned plan and actual scopes.")
        if self.plan.status != "ratified":
            raise ValueError("A demo story must identify its simulated approved baseline.")
        cells = {cell.id for cell in self.plan.cells}
        if any(link.from_cell_id not in cells for link in self.context_links):
            raise ValueError("Context links must start from a configured plan cell.")
        return self


class DemoPack(Contract):
    schema_version: Literal[1] = 1
    pack_id: Name
    label: Name
    description: str = Field(min_length=20, max_length=500)
    controls: DemoControls = Field(default_factory=DemoControls)
    stories: list[DemoStory] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_stories(self):
        ids = [story.story_id for story in self.stories]
        if len(ids) != len(set(ids)):
            raise ValueError("Demo story IDs must be unique.")
        return self


DEFAULT_ROOT = Path(__file__).parent / "config_packs" / "demo" / "configured-distribution.v1"
DEFAULT_PACK = DEFAULT_ROOT / "pack.json"


def load_pack(path: Path = DEFAULT_PACK) -> DemoPack:
    return DemoPack.model_validate_json(path.read_text(encoding="utf-8"))


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _story(pack: DemoPack, story_id: str) -> DemoStory:
    for story in pack.stories:
        if story.story_id == story_id:
            return story
    raise KeyError(story_id)


def _analysis(story: DemoStory, source_root: Path) -> dict:
    result = evaluate(
        story.plan, story.actuals, source_root=source_root,
        company_id=story.plan.company_id, as_of=story.actuals.recorded_on,
    )
    result["actual_revision"] = story.actuals.revision
    result["plan_import_digest"] = result["plan_hash"]
    result["actual_import_digest"] = result["actuals_hash"]
    return result


def build_catalog(pack: DemoPack | None = None, *, source_root: Path = DEFAULT_ROOT) -> dict:
    pack = pack or load_pack()
    stories = []
    for story in pack.stories:
        result = _analysis(story, source_root)
        stories.append({
            "story_id": story.story_id, "title": story.title, "question": story.question,
            "decision_prompt": story.decision_prompt, "analysis_hash": result["analysis_hash"],
            "rollups": result["rollups"],
            "finding_types": sorted({item["finding_type"] for item in result["findings"]}),
            "context_link_count": len(story.context_links),
        })
    payload = {
        "schema_version": pack.schema_version, "pack_id": pack.pack_id, "label": pack.label,
        "description": pack.description, "controls": pack.controls.model_dump(mode="json"),
        "stories": stories,
    }
    payload["catalog_digest"] = hashlib.sha256(_canonical(payload)).hexdigest()
    return payload


def story_detail(story_id: str, pack: DemoPack | None = None, *, source_root: Path = DEFAULT_ROOT) -> dict:
    pack = pack or load_pack()
    story = _story(pack, story_id)
    result = _analysis(story, source_root)
    base = "/api/demo-packs/current/stories/" + story.story_id + "/evidence"
    board = compose_snapshot(
        result, PackRequest(template=story.board_template, language="bilingual"),
        analysis_id=result["analysis_hash"], plan_digest=result["plan_hash"],
        actual_digest=result["actuals_hash"],
        evidence_url=lambda side, cell_id: base + "?" + urlencode({"side": side, "cell_id": cell_id}),
    )
    return {
        "pack_id": pack.pack_id, "mode": pack.controls.mode,
        "authority_effect": pack.controls.authority_effect,
        "sector_layer": pack.controls.sector_layer,
        "story": {
            "story_id": story.story_id, "title": story.title, "question": story.question,
            "decision_prompt": story.decision_prompt,
            "context_links": [item.model_dump(mode="json") for item in story.context_links],
        },
        "analysis": result, "board_pack": board,
    }


def evidence(story_id: str, side: Literal["plan", "actuals"], cell_id: str,
             pack: DemoPack | None = None, *, source_root: Path = DEFAULT_ROOT):
    pack = pack or load_pack()
    story = _story(pack, story_id)
    if side == "plan":
        item = next((cell for cell in story.plan.cells if cell.id == cell_id), None)
    else:
        plan_cell = next((cell for cell in story.plan.cells if cell.id == cell_id), None)
        item = next((row for row in story.actuals.observations
                     if plan_cell and row.metric == plan_cell.metric and row.dimensions == plan_cell.dimensions), None)
    if item is None:
        raise KeyError(cell_id)
    source = item.source
    verify_source(source_root.resolve(strict=True), source)
    return (source_root / source.path).resolve(), source
