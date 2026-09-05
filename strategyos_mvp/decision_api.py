"""Source-bound decision choices and reviewer-verified action evidence."""
import hashlib
from pathlib import Path
from typing import Any
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from .auth import require_role
from . import decision_lifecycle as store

router = APIRouter()

class Choice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=1, max_length=160)
    decision_key: str = Field(min_length=1, max_length=160)
    choice: str = Field(min_length=1, max_length=80)

class ActionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=1, max_length=160)
    decision_key: str = Field(min_length=1, max_length=160)
    artifact_key: str = Field(min_length=1, max_length=160)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verification_note: str = Field(min_length=20, max_length=2000)


def _current(run_id=None):
    from . import api
    summary = api.load_latest_run_summary()
    current = str((summary or {}).get("_backing_run_id") or (summary or {}).get("run_id") or "")
    if not current or (run_id and current != run_id):
        raise HTTPException(409, "Refresh to the current governed run before recording a decision.")
    decisions = (summary.get("strategy_enrichment") or {}).get("decision_seeds") or []
    return current, summary, {str(item["key"]): item for item in decisions}


def _perform(operation):
    try:
        return operation()
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/api/decision-lifecycle")
def read(principal: dict[str, Any] = require_role("executive")):
    run, _, decisions = _current()
    return {**_perform(lambda: store.read(run)), "available_decisions": list(decisions.values())}


@router.post("/api/decision-lifecycle/observe")
def observe(principal: dict[str, Any] = require_role("executive")):
    run, _, decisions = _current()
    for key, item in decisions.items():
        _perform(lambda: store.append(run, key, "surfaced", actor=str(principal["subject"]),
            payload={"title": item.get("title"), "evidence_refs": item.get("evidence_refs", [])}, effect_key="first-observation"))
    return _perform(lambda: store.read(run))


@router.post("/api/decision-lifecycle/choice")
def choose(request: Choice, principal: dict[str, Any] = require_role("executive"),
           idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    if not idempotency_key or len(idempotency_key) > 200:
        raise HTTPException(400, "A bounded Idempotency-Key is required.")
    run, _, decisions = _current(request.run_id)
    decision = decisions.get(request.decision_key)
    if not decision:
        raise HTTPException(404, "Decision not found in this run.")
    if request.choice not in decision.get("choices", []):
        raise HTTPException(422, "Choose an available decision option.")
    result = _perform(lambda: store.append(run, request.decision_key, "decided", actor=str(principal["subject"]),
        payload={"choice": request.choice, "owner": decision.get("owner") or decision.get("raised_by"),
                 "source_decision": decision}, effect_key=idempotency_key))
    return {**result, "delivery_status": "not_connected", "issue_status": "open"}


@router.post("/api/decision-lifecycle/verify-action")
def verify(request: ActionEvidence, principal: dict[str, Any] = require_role("reviewer")):
    from . import api
    from .access_scope import guard_run
    guard_run(request.run_id, require_store=True)
    summary = api._qa_summary_for_run(request.run_id)
    if summary.get("approval_status") != "approved":
        raise HTTPException(409, "Action evidence must belong to an approved run.")
    artifact = (summary.get("artifacts") or {}).get(request.artifact_key)
    root = Path(str(summary.get("run_dir") or "")).resolve()
    path = Path(str(artifact or "")).resolve()
    if not root.is_relative_to(api.CONFIG.output_root.resolve()) or not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404, "Approved action evidence was not found.")
    if hashlib.sha256(path.read_bytes()).hexdigest() != request.sha256:
        raise HTTPException(409, "The evidence changed. Review its current contents before verifying.")
    return _perform(lambda: store.append(request.run_id, request.decision_key, "action_verified",
        actor=str(principal["subject"]), effect_key="verified-first-action",
        payload={"evidence_path": request.artifact_key, "evidence_sha256": request.sha256,
                 "verification_note": request.verification_note}))

