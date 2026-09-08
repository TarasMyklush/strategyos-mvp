"""Authenticated, read-only API for configured synthetic decision stories."""
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from .auth import require_role
from . import demo_pack

router = APIRouter(prefix="/api/demo-packs", tags=["Demo packs"])
READ_ROLES = ("operator", "reviewer", "executive", "tenant_admin", "system")


@router.get("/current")
def current_pack(_: dict[str, Any] = require_role(*READ_ROLES)):
    return demo_pack.build_catalog()


@router.get("/current/stories/{story_id}")
def current_story(story_id: str, _: dict[str, Any] = require_role(*READ_ROLES)):
    try:
        return demo_pack.story_detail(story_id)
    except KeyError as exc:
        raise HTTPException(404, "Configured demo story was not found.") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/current/stories/{story_id}/evidence")
def story_evidence(story_id: str, side: Literal[
        "plan", "actuals", "plan_price", "plan_volume", "actual_price", "actual_volume"] = Query(),
                   cell_id: str = Query(min_length=1, max_length=160),
                   _: dict[str, Any] = require_role(*READ_ROLES)):
    try:
        path, source = demo_pack.evidence(story_id, side, cell_id)
    except KeyError as exc:
        raise HTTPException(404, "Configured demo evidence was not found.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return FileResponse(
        path, media_type="text/csv", filename=path.name,
        headers={"Cache-Control": "private, no-store", "X-Kyvern-Source-SHA256": source.sha256},
    )
