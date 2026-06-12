from __future__ import annotations

import json
import mimetypes
import re
import shutil
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from fastapi import HTTPException, UploadFile, status
import pandas as pd
from pypdf import PdfReader

from .config import CONFIG
from .data_roles import (
    cash_forecast_sheet_names,
    document_target_folders,
    role_labels,
    role_target_paths,
    run_model_required_roles,
    tabular_role_aliases,
    tabular_role_columns,
)
from .evidence import sha256_file
from .ocr import ocr_empty_pdf_pages, ocr_image_file
from .plugins import load_configured_plugins
from .prompt_injection import guard_untrusted_document_text, raw_document_text
from .tasks import (
    blocked_task_items_for_empty_source_pack,
    evaluate_task_readiness_items,
)

SUPPORTED_EXTENSIONS = {
    ".csv",
    ".json",
    ".md",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".txt",
    ".tsv",
    ".xls",
    ".xlsx",
}
TABULAR_EXTENSIONS = {".csv", ".json", ".tsv", ".xls", ".xlsx"}
DOCUMENT_EXTENSIONS = {".md", ".pdf", ".txt"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
IGNORED_NAMES = {".DS_Store"}
OVERRIDE_FILENAME = "mapping_overrides.json"

ROLE_LABELS = role_labels()
ROLE_TARGET_PATHS = role_target_paths()
DOCUMENT_TARGET_FOLDERS = document_target_folders()
RUN_MODEL_REQUIRED_ROLES = run_model_required_roles()
TABULAR_ROLE_COLUMNS = tabular_role_columns()

TABULAR_ROLE_SIGNATURES = {
    role: set(columns) for role, columns in TABULAR_ROLE_COLUMNS.items()
}

ROLE_COLUMN_ALIASES = tabular_role_aliases()
CASH_FORECAST_SHEET_NAMES = cash_forecast_sheet_names()


def refresh_source_pack_role_constants() -> None:
    global ROLE_LABELS
    global ROLE_TARGET_PATHS
    global DOCUMENT_TARGET_FOLDERS
    global RUN_MODEL_REQUIRED_ROLES
    global TABULAR_ROLE_COLUMNS
    global TABULAR_ROLE_SIGNATURES
    global ROLE_COLUMN_ALIASES
    global CASH_FORECAST_SHEET_NAMES
    ROLE_LABELS = role_labels()
    ROLE_TARGET_PATHS = role_target_paths()
    DOCUMENT_TARGET_FOLDERS = document_target_folders()
    RUN_MODEL_REQUIRED_ROLES = run_model_required_roles()
    TABULAR_ROLE_COLUMNS = tabular_role_columns()
    TABULAR_ROLE_SIGNATURES = {
        role: set(columns) for role, columns in TABULAR_ROLE_COLUMNS.items()
    }
    ROLE_COLUMN_ALIASES = tabular_role_aliases()
    CASH_FORECAST_SHEET_NAMES = cash_forecast_sheet_names()


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _source_packs_root() -> Path:
    root = CONFIG.output_root / "source_packs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _source_pack_dir(source_pack_id: str) -> Path:
    return (_source_packs_root() / source_pack_id).resolve()


def _raw_dir(source_pack_id: str) -> Path:
    return _source_pack_dir(source_pack_id) / "raw"


def _manifest_path(source_pack_id: str) -> Path:
    return _source_pack_dir(source_pack_id) / "manifest.json"


def _summary_path(source_pack_id: str) -> Path:
    return _source_pack_dir(source_pack_id) / "summary.json"


def _task_readiness_path(source_pack_id: str) -> Path:
    return _source_pack_dir(source_pack_id) / "task_readiness.json"


def _normalized_dataset_root(source_pack_id: str) -> Path:
    return _source_pack_dir(source_pack_id) / "normalized" / "current_run_model"


def _partial_dataset_root(source_pack_id: str) -> Path:
    return _source_pack_dir(source_pack_id) / "normalized" / "partial_run_model"


def _mapping_overrides_path(source_pack_id: str) -> Path:
    return _source_pack_dir(source_pack_id) / OVERRIDE_FILENAME


def _normalize_upload_path(filename: str) -> PurePosixPath:
    normalized = (filename or "").replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if not normalized or normalized in {".", "/"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded files must include a relative source-pack path.",
        )
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file paths must stay relative to the selected source pack.",
        )
    return path


def _iter_source_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith(".") or path.name in IGNORED_NAMES:
            continue
        yield path


def _file_type_hint(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in TABULAR_EXTENSIONS:
        if suffix in {".xls", ".xlsx"}:
            return "spreadsheet"
        if suffix == ".csv":
            return "csv"
        if suffix == ".tsv":
            return "tsv"
        return "json"
    if suffix in DOCUMENT_EXTENSIONS:
        if suffix == ".pdf":
            return "pdf"
        if suffix == ".md":
            return "markdown"
        return "text"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    return "unsupported"


def _extraction_status(path: Path) -> str:
    hint = _file_type_hint(path)
    if hint in {"pdf", "image", "text", "markdown"}:
        return "pending"
    if hint == "unsupported":
        return "unsupported"
    return "not_requested"


def _source_id(source_pack_id: str, relative_path: str, sha256_value: str) -> str:
    return sha256(
        f"{source_pack_id}\0{relative_path}\0{sha256_value}".encode("utf-8")
    ).hexdigest()[:16]


def _deterministic_source_pack_id(entries: list[dict[str, Any]]) -> str:
    hasher = sha256()
    for entry in sorted(entries, key=lambda item: str(item["relative_path"])):
        hasher.update(str(entry["relative_path"]).encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(str(entry["sha256"]).encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(str(entry["size_bytes"]).encode("utf-8"))
        hasher.update(b"\n")
    return hasher.hexdigest()


def _build_manifest(raw_root: Path, *, source_pack_id: str) -> list[dict[str, Any]]:
    ingested_at = datetime.now(UTC).isoformat()
    manifest: list[dict[str, Any]] = []
    for path in _iter_source_files(raw_root):
        rel = path.relative_to(raw_root).as_posix()
        digest = sha256_file(path)
        hint = _file_type_hint(path)
        supported = path.suffix.lower() in SUPPORTED_EXTENSIONS
        manifest.append(
            {
                "source_id": _source_id(source_pack_id, rel, digest),
                "relative_path": rel,
                "staged_path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256": digest,
                "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                "file_type_hint": hint,
                "supported": supported,
                "extraction_status": _extraction_status(path),
                "issues": [] if supported else ["Unsupported file type."],
                "ingested_at": ingested_at,
            }
        )
    return manifest


def _read_tabular_preview(path: Path) -> tuple[list[str], set[str], str | None]:
    try:
        if path.suffix.lower() == ".csv":
            frame = pd.read_csv(path, nrows=5)
            return [str(column) for column in frame.columns], set(), None
        if path.suffix.lower() == ".tsv":
            frame = pd.read_csv(path, sep="\t", nrows=5)
            return [str(column) for column in frame.columns], set(), None
        if path.suffix.lower() == ".json":
            frame = pd.read_json(path)
            return [str(column) for column in frame.columns], set(), None
        workbook = pd.ExcelFile(path)
        sheet_names = {str(name) for name in workbook.sheet_names}
        frame = workbook.parse(workbook.sheet_names[0], nrows=5) if workbook.sheet_names else pd.DataFrame()
        return [str(column) for column in frame.columns], sheet_names, None
    except Exception as exc:
        return [], set(), str(exc)


def _normalized_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).strip().lower())


def _alias_candidates(role: str, canonical_column: str) -> list[str]:
    aliases = ROLE_COLUMN_ALIASES.get(role, {}).get(canonical_column, [])
    return [canonical_column, *aliases]


def _propose_column_mapping(role: str, columns: list[str]) -> dict[str, Any]:
    source_by_token: dict[str, str] = {}
    direct_matches = 0
    alias_matches = 0
    mapping: dict[str, str] = {}
    matched_required: list[str] = []
    seen_sources: set[str] = set()

    for source_column in columns:
        source_by_token.setdefault(_normalized_token(source_column), source_column)

    for canonical_column in TABULAR_ROLE_COLUMNS[role]:
        chosen: str | None = None
        for alias in _alias_candidates(role, canonical_column):
            candidate = source_by_token.get(_normalized_token(alias))
            if candidate and candidate not in seen_sources:
                chosen = candidate
                if candidate == canonical_column:
                    direct_matches += 1
                else:
                    alias_matches += 1
                break
        if chosen is None:
            continue
        mapping[canonical_column] = chosen
        matched_required.append(canonical_column)
        seen_sources.add(chosen)

    required_columns = list(TABULAR_ROLE_COLUMNS[role])
    missing_required = [column for column in required_columns if column not in mapping]
    coverage = len(mapping) / len(required_columns) if required_columns else 0.0
    requires_confirmation = bool(alias_matches or missing_required)
    return {
        "role": role,
        "label": ROLE_LABELS[role],
        "coverage": round(coverage, 3),
        "confidence": round(coverage, 3),
        "column_mapping": mapping,
        "matched_required": sorted(matched_required),
        "missing_required": missing_required,
        "direct_match_count": direct_matches,
        "alias_match_count": alias_matches,
        "source_columns": columns,
        "unmapped_source_columns": [column for column in columns if column not in seen_sources],
        "requires_confirmation": requires_confirmation,
    }


def _load_mapping_overrides(source_pack_id: str) -> dict[str, dict[str, Any]]:
    path = _mapping_overrides_path(source_pack_id)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): value for key, value in payload.items() if isinstance(value, dict)}


def _save_mapping_overrides(source_pack_id: str, overrides: dict[str, dict[str, Any]]) -> None:
    path = _mapping_overrides_path(source_pack_id)
    path.write_text(json.dumps(overrides, indent=2), encoding="utf-8")


def _build_structured_classification(
    *,
    role: str,
    proposal: dict[str, Any],
    confirmed: bool = False,
) -> dict[str, Any]:
    exact_match = not proposal.get("requires_confirmation") and not proposal.get("missing_required")
    if confirmed:
        status_value = "classified"
        basis = f"Operator confirmed canonical column mapping for the {ROLE_LABELS[role].lower()}."
    elif exact_match:
        status_value = "classified"
        basis = (
            f"Structured columns matched the {ROLE_LABELS[role].lower()} signature: "
            + ", ".join(sorted(TABULAR_ROLE_SIGNATURES[role]))
            + "."
        )
    else:
        status_value = "candidate"
        basis = (
            f"Structured columns suggest the {ROLE_LABELS[role].lower()} role with "
            f"{int(round(float(proposal['coverage']) * 100))}% required-column coverage."
        )
    issues = []
    if proposal.get("missing_required"):
        issues.append(
            "Structured source is missing required canonical columns: "
            + ", ".join(proposal["missing_required"])
            + "."
        )
    if proposal.get("requires_confirmation") and not confirmed:
        issues.append("Structured source requires operator mapping confirmation before canonical normalization.")
    return {
        **_classified_entry(
            status_value=status_value,
            role=role,
            confidence=float(proposal["confidence"]),
            basis=basis,
            normalized_rel_path=ROLE_TARGET_PATHS.get(role),
            issues=issues,
        ),
        "column_mapping_proposal": proposal,
    }


def _extract_text_sample(path: Path, *, max_chars: int = 8000) -> tuple[str, str | None]:
    suffix = path.suffix.lower()
    try:
        if suffix in {".txt", ".md"}:
            return path.read_text(encoding="utf-8", errors="ignore")[:max_chars], None
        if suffix == ".pdf":
            reader = PdfReader(str(path))
            pages: list[str] = []
            for page in reader.pages[:5]:
                pages.append(page.extract_text() or "")
            return "\n".join(pages)[:max_chars], None
    except Exception as exc:
        return "", str(exc)
    return "", None


def _combined_extracted_text(records: list[dict[str, Any]], *, max_chars: int = 8000) -> str:
    return "\n".join(
        str(record.get("raw_text") or record.get("extracted_text") or "")
        for record in records
        if str(record.get("raw_text") or record.get("extracted_text") or "").strip()
    )[:max_chars]


def _guard_text_record(record: dict[str, Any], *, source_name: str, max_chars: int = 8000) -> dict[str, Any]:
    guarded = guard_untrusted_document_text(
        str(record.get("extracted_text") or ""),
        source_name=source_name,
        max_chars=max_chars,
    )
    updated = dict(record)
    updated["raw_text"] = guarded["raw_text"]
    updated["extracted_text"] = guarded["guarded_text"]
    updated["prompt_injection_guard"] = {
        "status": guarded["status"],
        "treat_as": guarded["treat_as"],
        "contains_prompt_injection_signals": guarded[
            "contains_prompt_injection_signals"
        ],
        "detected_signals": guarded["detected_signals"],
    }
    return updated


def _guard_text_extraction_payload(
    extraction: dict[str, Any], *, source_name: str, max_chars: int = 8000
) -> dict[str, Any]:
    guarded_pages = [
        _guard_text_record(
            page,
            source_name=f"{source_name} page {page.get('page', index)}",
            max_chars=max_chars,
        )
        for index, page in enumerate(extraction.get("pages", []), start=1)
    ]
    guarded = guard_untrusted_document_text(
        _combined_extracted_text(guarded_pages, max_chars=max_chars),
        source_name=source_name,
        max_chars=max_chars,
    )
    return {
        **extraction,
        "pages": guarded_pages,
        "raw_text": guarded["raw_text"],
        "extracted_text": guarded["guarded_text"],
        "prompt_injection_guard": {
            "status": guarded["status"],
            "treat_as": guarded["treat_as"],
            "contains_prompt_injection_signals": guarded[
                "contains_prompt_injection_signals"
            ],
            "detected_signals": guarded["detected_signals"],
        },
    }


def _summarize_text_extraction(records: list[dict[str, Any]], *, max_chars: int = 8000) -> dict[str, Any]:
    extracted_text = _combined_extracted_text(records, max_chars=max_chars)
    statuses = {str(record.get("status") or "") for record in records}
    engines = [str(record.get("engine")) for record in records if record.get("engine")]
    failure_reasons = [
        str(record.get("failure_reason") or "")
        for record in records
        if str(record.get("failure_reason") or "").strip()
    ]
    if not records:
        status_value = "not_requested"
    elif statuses == {"ok"}:
        status_value = "ok"
    elif statuses <= {"empty"}:
        status_value = "empty"
    elif "ok" in statuses and statuses - {"ok"}:
        status_value = "partial"
    elif "failed" in statuses:
        status_value = "failed"
    else:
        status_value = next(iter(statuses), "unknown")
    return {
        "status": status_value,
        "engine": engines[0] if len(set(engines)) == 1 and engines else "mixed" if engines else None,
        "extracted_text": extracted_text,
        "failure_reason": "; ".join(dict.fromkeys(failure_reasons)) or None,
        "pages": records,
    }


def _extract_pdf_text_records(path: Path, *, max_chars: int = 8000) -> dict[str, Any]:
    try:
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        return {
            "status": "failed",
            "engine": "pypdf",
            "extracted_text": "",
            "failure_reason": str(exc),
            "pages": [
                {
                    "page": 1,
                    "status": "failed",
                    "engine": "pypdf",
                    "extracted_text": "",
                    "failure_reason": str(exc),
                }
            ],
        }

    base_records = [
        {
            "page": page_no,
            "status": "ok" if text.strip() else "empty",
            "engine": "pypdf",
            "extracted_text": text[:max_chars],
            "failure_reason": None,
        }
        for page_no, text in enumerate(pages, start=1)
    ]
    updated_pages, ocr_status = ocr_empty_pdf_pages(path, pages)
    ocr_pages = {int(item["page"]): item for item in ocr_status.get("pages", [])}
    blocked_reason = ocr_status.get("blocked_reason")
    records: list[dict[str, Any]] = []
    for page_no, record in enumerate(base_records, start=1):
        if record["status"] == "ok":
            records.append(record)
            continue
        ocr_page = ocr_pages.get(page_no)
        if ocr_page is not None:
            records.append(
                {
                    "page": page_no,
                    "status": ocr_page.get("status") or "failed",
                    "engine": ocr_page.get("engine"),
                    "extracted_text": str(updated_pages[page_no - 1] or "")[:max_chars],
                    "failure_reason": ocr_page.get("detail") or None,
                }
            )
        elif blocked_reason:
            records.append(
                {
                    "page": page_no,
                    "status": "failed",
                    "engine": ocr_status.get("engine"),
                    "extracted_text": "",
                    "failure_reason": blocked_reason,
                }
            )
        else:
            records.append(record)
    return _summarize_text_extraction(records, max_chars=max_chars)


def _extract_image_text_records(path: Path, *, max_chars: int = 8000) -> dict[str, Any]:
    ocr_status = ocr_image_file(path)
    blocked_reason = ocr_status.get("blocked_reason")
    ocr_page = next(iter(ocr_status.get("pages", [])), None)
    record = {
        "page": 1,
        "status": "failed" if blocked_reason else (ocr_page or {}).get("status") or "failed",
        "engine": (ocr_page or {}).get("engine") or ocr_status.get("engine"),
        "extracted_text": str((ocr_page or {}).get("text") or "")[:max_chars],
        "failure_reason": blocked_reason or (ocr_page or {}).get("detail") or None,
    }
    return _summarize_text_extraction([record], max_chars=max_chars)


def _attach_text_extraction(manifest: list[dict[str, Any]], raw_root: Path) -> None:
    for item in manifest:
        if not item.get("supported"):
            continue
        path = raw_root / str(item["relative_path"])
        hint = str(item.get("file_type_hint") or "")
        extraction: dict[str, Any] | None = None
        if hint == "pdf":
            extraction = _extract_pdf_text_records(path)
        elif hint == "image":
            extraction = _extract_image_text_records(path)
        if extraction is None:
            continue
        extraction = _guard_text_extraction_payload(
            extraction,
            source_name=str(item["relative_path"]),
        )
        item["text_extraction"] = extraction
        item["extraction_status"] = extraction["status"]
        if extraction.get("failure_reason"):
            issue = "Source text extraction recorded a recoverable failure; see text_extraction for details."
            if issue not in item["issues"]:
                item["issues"].append(issue)


def _classified_entry(
    *,
    status_value: str,
    role: str | None,
    confidence: float,
    basis: str,
    normalized_rel_path: str | None = None,
    issues: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": status_value,
        "role": role,
        "label": ROLE_LABELS.get(role, "Unknown") if role else None,
        "confidence": round(float(confidence), 3),
        "basis": basis,
        "normalized_rel_path": normalized_rel_path,
        "issues": issues or [],
    }


def _classify_structured_source(path: Path) -> dict[str, Any] | None:
    columns, sheet_names, error = _read_tabular_preview(path)
    if error:
        return _classified_entry(
            status_value="unclassified",
            role=None,
            confidence=0.0,
            basis=f"Structured preview failed: {error}",
            issues=["Structured preview failed during classification."],
        )

    normalized_sheet_names = {name.strip().lower() for name in sheet_names}
    if normalized_sheet_names and CASH_FORECAST_SHEET_NAMES.issubset(normalized_sheet_names):
        classification = _classified_entry(
            status_value="classified",
            role="cash_forecast",
            confidence=1.0,
            basis="Workbook sheet names match the cash-forecast structure.",
            normalized_rel_path=ROLE_TARGET_PATHS["cash_forecast"],
        )
        classification["column_mapping_proposal"] = None
        return classification

    proposals = [_propose_column_mapping(role, columns) for role in TABULAR_ROLE_SIGNATURES]
    proposals.sort(
        key=lambda item: (float(item["coverage"]), int(item["direct_match_count"]), -int(item["alias_match_count"])),
        reverse=True,
    )
    best = proposals[0] if proposals else None
    candidate_threshold = CONFIG.source_pack_structured_candidate_threshold
    if best and float(best["coverage"]) >= candidate_threshold:
        classification = _build_structured_classification(role=str(best["role"]), proposal=best)
        classification["role_candidates"] = proposals[:3]
        return classification

    best_score = float(best["coverage"]) if best else 0.0
    return _classified_entry(
        status_value="unclassified",
        role=None,
        confidence=best_score,
        basis="Structured columns did not match any current run-model role signature.",
        issues=["Content-based classification could not assign a structured source role."],
    )


def _text_role_score(text: str, patterns: tuple[str, ...]) -> int:
    return sum(1 for pattern in patterns if re.search(pattern, text, re.I))


def _classify_document_source(path: Path, item: dict[str, Any]) -> dict[str, Any]:
    text_extraction = item.get("text_extraction") or {}
    text = raw_document_text(text_extraction)
    error = None
    if not text and path.suffix.lower() in {".txt", ".md"}:
        text, error = _extract_text_sample(path)
    if error:
        return _classified_entry(
            status_value="unclassified",
            role=None,
            confidence=0.0,
            basis=f"Document text extraction failed during classification: {error}",
            issues=["Document text extraction failed during classification."],
        )
    compact = " ".join(text.split())
    if not compact:
        return _classified_entry(
            status_value="unclassified",
            role=None,
            confidence=0.0,
            basis="Document text was empty after extraction, so content-based classification could not assign a role.",
            issues=["Document classification requires extractable text or OCR-backed text."],
        )

    scores = {
        "invoice_document": _text_role_score(compact, (r"\binvoice\b", r"invoice\s*(number|no\.?|id)", r"\bbill to\b", r"\bamount due\b")),
        "bank_statement": _text_role_score(compact, (r"\bstatement\b", r"\bbank\b", r"\baccount\b", r"\bbalance\b")),
        "contract": _text_role_score(compact, (r"\bcontract\b", r"\bagreement\b", r"effective date", r"payment terms")),
        "email_correspondence": _text_role_score(compact, (r"\bfrom:\b", r"\bsubject:\b", r"\bdear\b", r"\bregards\b", r"@")),
    }
    best_role = max(scores, key=scores.get)
    best_score = scores[best_role]
    winners = [role for role, score in scores.items() if score == best_score and score > 0]
    if best_score >= CONFIG.source_pack_document_indicator_threshold and len(winners) == 1:
        folder = DOCUMENT_TARGET_FOLDERS[best_role]
        return _classified_entry(
            status_value="classified",
            role=best_role,
            confidence=min(1.0, best_score / 4),
            basis=f"Document text matched {ROLE_LABELS[best_role].lower()} indicators in extracted content.",
            normalized_rel_path=f"{folder}/{path.name}",
        )
    if len(winners) > 1:
        return _classified_entry(
            status_value="ambiguous",
            role=None,
            confidence=min(1.0, best_score / 4),
            basis=f"Document text overlapped multiple role indicators: {', '.join(sorted(ROLE_LABELS[role] for role in winners))}.",
            issues=["Document content matched multiple supported role patterns."],
        )
    return _classified_entry(
        status_value="unclassified",
        role=None,
        confidence=min(1.0, best_score / 4),
        basis="Document text did not reach the current content-based role threshold.",
        issues=["Document content did not match a supported role strongly enough."],
    )


def _classify_manifest(manifest: list[dict[str, Any]], raw_root: Path, *, source_pack_id: str) -> None:
    _attach_text_extraction(manifest, raw_root)
    overrides = _load_mapping_overrides(source_pack_id)
    for item in manifest:
        if not item.get("supported"):
            item["classification"] = _classified_entry(
                status_value="unsupported",
                role=None,
                confidence=0.0,
                basis="Unsupported file types are retained for visibility but are not classified.",
                issues=list(item.get("issues") or []),
            )
            continue
        path = raw_root / str(item["relative_path"])
        hint = str(item.get("file_type_hint") or "")
        if hint in {"spreadsheet", "csv", "tsv", "json"}:
            classification = _classify_structured_source(path)
        elif hint in {"pdf", "text", "markdown", "image"}:
            classification = _classify_document_source(path, item)
        else:
            classification = _classified_entry(
                status_value="unclassified",
                role=None,
                confidence=0.0,
                basis="Current content-based classification only covers structured files plus extractable text-bearing documents.",
                issues=["Content-based classification does not yet cover this source type."],
            )
        override = overrides.get(str(item["relative_path"]))
        if override and hint in {"spreadsheet", "csv", "tsv", "json"}:
            role = str(override.get("role") or "")
            columns, _sheet_names, _error = _read_tabular_preview(path)
            proposal = _propose_column_mapping(role, columns) if role in TABULAR_ROLE_SIGNATURES else None
            mapped_columns = override.get("column_mapping") or {}
            if proposal is not None:
                proposal["column_mapping"] = {
                    str(key): str(value) for key, value in mapped_columns.items() if str(value).strip()
                }
                proposal["matched_required"] = sorted(proposal["column_mapping"])
                proposal["missing_required"] = [
                    column for column in sorted(TABULAR_ROLE_SIGNATURES[role]) if column not in proposal["column_mapping"]
                ]
                proposal["requires_confirmation"] = False
                proposal["confirmed_at"] = override.get("confirmed_at")
                classification = _build_structured_classification(role=role, proposal=proposal, confirmed=True)
        item["classification"] = classification
        for issue in classification.get("issues") or []:
            if issue not in item["issues"]:
                item["issues"].append(issue)


def _classification_summary(manifest: list[dict[str, Any]]) -> dict[str, Any]:
    counts_by_status: dict[str, int] = {}
    counts_by_role: dict[str, int] = {}
    for item in manifest:
        classification = item.get("classification") or {}
        status_value = str(classification.get("status") or "unclassified")
        counts_by_status[status_value] = counts_by_status.get(status_value, 0) + 1
        role = classification.get("role")
        if role:
            counts_by_role[str(role)] = counts_by_role.get(str(role), 0) + 1
    return {
        "counts_by_status": counts_by_status,
        "counts_by_role": counts_by_role,
    }


def _role_inventory(manifest: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    inventory: dict[str, list[dict[str, Any]]] = {}
    for item in manifest:
        classification = item.get("classification") or {}
        if classification.get("status") != "classified" or not classification.get("role"):
            continue
        inventory.setdefault(str(classification["role"]), []).append(item)
    return inventory


def _load_structured_frame(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".tsv":
        return pd.read_csv(path, sep="\t")
    if suffix == ".json":
        return pd.read_json(path)
    return pd.read_excel(path)


def _write_structured_frame(frame: pd.DataFrame, destination: Path) -> None:
    if destination.suffix.lower() == ".csv":
        frame.to_csv(destination, index=False)
    else:
        frame.to_excel(destination, index=False)


def _canonicalize_structured_file(
    source_path: Path,
    destination: Path,
    *,
    role: str,
    column_mapping: dict[str, str],
) -> None:
    frame = _load_structured_frame(source_path)
    rename_map = {str(source): canonical for canonical, source in column_mapping.items()}
    renamed = frame.rename(columns=rename_map)
    ordered_columns = [column for column in TABULAR_ROLE_COLUMNS.get(role, ()) if column in renamed.columns]
    remaining_columns = [column for column in renamed.columns if column not in ordered_columns]
    canonicalized = renamed.loc[:, ordered_columns + remaining_columns]
    _write_structured_frame(canonicalized, destination)


def _normalize_manifest(manifest: list[dict[str, Any]], raw_root: Path, *, source_pack_id: str) -> dict[str, Any]:
    normalized_root = _normalized_dataset_root(source_pack_id)
    if normalized_root.exists():
        shutil.rmtree(normalized_root)
    normalized_root.mkdir(parents=True, exist_ok=True)

    copied_targets: dict[str, str] = {}
    inventory = _role_inventory(manifest)
    duplicates = sorted(role for role, items in inventory.items() if role in ROLE_TARGET_PATHS and len(items) > 1)

    for item in manifest:
        classification = item.get("classification") or {}
        if classification.get("status") != "classified":
            continue
        normalized_rel_path = classification.get("normalized_rel_path")
        role = classification.get("role")
        if not normalized_rel_path:
            continue
        if role in duplicates:
            item["issues"].append(f"Multiple files classified as {ROLE_LABELS[role].lower()}; run normalization requires exactly one.")
            continue
        destination = normalized_root / str(normalized_rel_path)
        final_rel_path = str(normalized_rel_path)
        if destination.exists() and role not in ROLE_TARGET_PATHS:
            destination = destination.with_name(f"{item['source_id']}__{destination.name}")
            final_rel_path = destination.relative_to(normalized_root).as_posix()
        destination.parent.mkdir(parents=True, exist_ok=True)
        source_path = raw_root / str(item["relative_path"])
        column_mapping = (classification.get("column_mapping_proposal") or {}).get("column_mapping") or {}
        if role in ROLE_TARGET_PATHS and column_mapping and source_path.suffix.lower() in TABULAR_EXTENSIONS and role != "cash_forecast":
            _canonicalize_structured_file(source_path, destination, role=str(role), column_mapping=column_mapping)
        else:
            shutil.copy2(source_path, destination)
        classification["normalized_rel_path"] = final_rel_path
        item["normalized_path"] = str(destination)
        copied_targets[final_rel_path] = str(item["relative_path"])

    present_required = {role for role in RUN_MODEL_REQUIRED_ROLES if role in inventory and len(inventory[role]) == 1}
    missing_required = sorted(role for role in RUN_MODEL_REQUIRED_ROLES if role not in present_required)
    return {
        "normalized_dataset_root": str(normalized_root),
        "normalized_files": copied_targets,
        "missing_required_roles": missing_required,
        "duplicate_required_roles": duplicates,
    }


def _build_partial_dataset(source_pack_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Stage a partial run dataset from ONLY the operator-supplied files.

    Missing roles are deliberately left absent — the loader fills them as empty
    canonical frames and the dependent detectors are skipped. We never inject
    the synthetic baseline dataset, so a real upload is never contaminated with
    fixture data.
    """
    current_root = Path(str(payload["normalized_dataset_root"]))
    partial_root = _partial_dataset_root(source_pack_id)
    if partial_root.exists():
        shutil.rmtree(partial_root)
    partial_root.mkdir(parents=True, exist_ok=True)
    if current_root.exists():
        for path in _iter_source_files(current_root):
            rel = path.relative_to(current_root)
            destination = partial_root / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)

    readiness = payload.get("task_readiness", {})
    missing_roles = sorted(str(role) for role in readiness.get("missing_run_model_roles", []))
    available_roles = sorted(
        role for role in RUN_MODEL_REQUIRED_ROLES if role not in set(missing_roles)
    )
    return {
        "dataset_root": str(partial_root),
        "run_mode": "partial" if missing_roles else "full",
        "available_roles": available_roles,
        "missing_roles": missing_roles,
    }


def _manifest_summary(manifest: list[dict[str, Any]]) -> dict[str, Any]:
    supported_count = sum(1 for item in manifest if item.get("supported"))
    unsupported_count = len(manifest) - supported_count
    counts_by_hint: dict[str, int] = {}
    pending_extraction = 0
    for item in manifest:
        hint = str(item.get("file_type_hint") or "unknown")
        counts_by_hint[hint] = counts_by_hint.get(hint, 0) + 1
        if item.get("extraction_status") == "pending":
            pending_extraction += 1
    return {
        "file_count": len(manifest),
        "supported_count": supported_count,
        "unsupported_count": unsupported_count,
        "supported_file_count": supported_count,
        "unsupported_file_count": unsupported_count,
        "pending_extraction_count": pending_extraction,
        "counts_by_hint": counts_by_hint,
    }


def _unconfirmed_roles(manifest: list[dict[str, Any]]) -> list[str]:
    """Structured roles whose auto-mapping is uncertain and not yet confirmed.

    A role is flagged when a manifest item proposes it as a structured target
    but the column mapping ``requires_confirmation`` (alias-only or incomplete
    match) and no operator override has been saved for it. Exact/high-confidence
    matches and operator-confirmed mappings are never flagged.
    """
    flagged: set[str] = set()
    for item in manifest:
        classification = item.get("classification") or {}
        proposal = classification.get("column_mapping_proposal") or {}
        role = proposal.get("role") or classification.get("role")
        if not role or role not in TABULAR_ROLE_SIGNATURES:
            continue
        if proposal.get("requires_confirmation"):
            flagged.add(str(role))
    return sorted(flagged)


def build_task_readiness(manifest: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _manifest_summary(manifest)
    supported_count = int(summary["supported_file_count"])
    inventory = _role_inventory(manifest)
    unconfirmed_roles = _unconfirmed_roles(manifest)
    structured_duplicates = sorted(
        role for role, items in inventory.items() if role in ROLE_TARGET_PATHS and len(items) > 1
    )
    missing_run_roles = sorted(
        role for role in RUN_MODEL_REQUIRED_ROLES if len(inventory.get(role, [])) != 1
    )
    has_role = lambda role: len(inventory.get(role, [])) >= 1
    run_ready = supported_count > 0 and not missing_run_roles and not structured_duplicates

    if supported_count == 0:
        tasks = blocked_task_items_for_empty_source_pack()
        overall = "blocked"
        ready_for_run = False
        classification_status = "empty"
        blocking_reasons = [
            "No supported files were registered in the staged source pack.",
        ]
    else:
        tasks = evaluate_task_readiness_items(has_role=has_role, run_ready=run_ready)
        overall = "ready" if run_ready else "partial"
        ready_for_run = run_ready
        classified_count = sum(
            1 for item in manifest if (item.get("classification") or {}).get("status") == "classified"
        )
        classification_status = "complete" if classified_count == supported_count else "partial"
        blocking_reasons = []
        if missing_run_roles:
            blocking_reasons.append(
                "Current run-model normalization is missing required structured roles: "
                + ", ".join(ROLE_LABELS[role] for role in missing_run_roles)
                + "."
            )
        if structured_duplicates:
            blocking_reasons.append(
                "Current run-model normalization found duplicate required roles: "
                + ", ".join(ROLE_LABELS[role] for role in structured_duplicates)
                + "."
            )

    return {
        "status": overall,
        "ready_for_run": ready_for_run,
        "classification_status": classification_status,
        "blocking_reasons": blocking_reasons,
        "basis": "content-based source classification plus current run-model normalization",
        "missing_run_model_roles": missing_run_roles,
        "duplicate_run_model_roles": structured_duplicates,
        "unconfirmed_roles": unconfirmed_roles,
        "tasks": tasks,
    }


def build_validation(manifest: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _manifest_summary(manifest)
    readiness = build_task_readiness(manifest)
    issues: list[str] = []
    if summary["file_count"] == 0:
        issues.append("The selected source pack was empty.")
    if summary["unsupported_file_count"]:
        issues.append(
            f"{summary['unsupported_file_count']} files are unsupported in the current source-pack intake slice and were retained for visibility."
        )
    if summary["pending_extraction_count"]:
        issues.append(
            f"{summary['pending_extraction_count']} files are staged with extraction pending for a later tranche."
        )
    if readiness["missing_run_model_roles"]:
        issues.append(
            "Current run-model normalization is missing required structured roles: "
            + ", ".join(ROLE_LABELS[role] for role in readiness["missing_run_model_roles"])
            + "."
        )
    if readiness["duplicate_run_model_roles"]:
        issues.append(
            "Current run-model normalization found duplicate required roles: "
            + ", ".join(ROLE_LABELS[role] for role in readiness["duplicate_run_model_roles"])
            + "."
        )
    status_value = "blocked" if summary["file_count"] == 0 else "ready" if readiness["ready_for_run"] else "partial"
    return {
        "status": status_value,
        "issues": issues,
        "notes": [
            "Validation confirms staging, content-based classification coverage, and normalization into the current run model.",
            "A source pack is runnable only when the required structured roles classify exactly once into the current run model.",
        ],
    }


def _write_summary(source_pack_id: str, payload: dict[str, Any]) -> None:
    pack_dir = _source_pack_dir(source_pack_id)
    pack_dir.mkdir(parents=True, exist_ok=True)
    _manifest_path(source_pack_id).write_text(
        json.dumps(payload["manifest"], indent=2), encoding="utf-8"
    )
    _task_readiness_path(source_pack_id).write_text(
        json.dumps(payload["task_readiness"], indent=2), encoding="utf-8"
    )
    _summary_path(source_pack_id).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _payload_for(source_pack_id: str, raw_root: Path, *, source_kind: str) -> dict[str, Any]:
    load_configured_plugins()
    refresh_source_pack_role_constants()
    manifest = _build_manifest(raw_root, source_pack_id=source_pack_id)
    _classify_manifest(manifest, raw_root, source_pack_id=source_pack_id)
    normalization = _normalize_manifest(manifest, raw_root, source_pack_id=source_pack_id)
    payload = {
        "status": "ok",
        "source_pack_id": source_pack_id,
        "source_kind": source_kind,
        "source_pack_root": str(_source_pack_dir(source_pack_id)),
        "raw_root": str(raw_root),
        "normalized_dataset_root": normalization["normalized_dataset_root"],
        "manifest_path": str(_manifest_path(source_pack_id)),
        "task_readiness_path": str(_task_readiness_path(source_pack_id)),
        "manifest": manifest,
        "manifest_summary": _manifest_summary(manifest),
        "classification_summary": _classification_summary(manifest),
        "task_readiness": build_task_readiness(manifest),
        "validation": build_validation(manifest),
    }
    _write_summary(source_pack_id, payload)
    return payload


def _copy_tree_to_raw(source_root: Path, raw_root: Path) -> None:
    for path in _iter_source_files(source_root):
        rel = path.relative_to(source_root)
        destination = raw_root / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def _source_pack_id_for_tree(source_root: Path) -> str:
    manifest_seed: list[dict[str, Any]] = []
    for path in _iter_source_files(source_root):
        manifest_seed.append(
            {
                "relative_path": path.relative_to(source_root).as_posix(),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return _deterministic_source_pack_id(manifest_seed)


def stage_source_pack_from_path(folder_path: str) -> dict[str, Any]:
    resolved = Path(folder_path).expanduser().resolve()
    if not _path_is_within(resolved, CONFIG.workspace_root):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source-pack folder path must stay within the configured workspace boundary.",
        )
    if not resolved.exists() or not resolved.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source-pack folder path must point to an existing directory.",
        )

    source_pack_id = _source_pack_id_for_tree(resolved)
    raw_root = _raw_dir(source_pack_id)
    raw_root.mkdir(parents=True, exist_ok=True)
    _copy_tree_to_raw(resolved, raw_root)
    return _payload_for(source_pack_id, raw_root, source_kind="workspace_path")


def _source_pack_id_for_uploads(files: list[UploadFile]) -> str:
    manifest_seed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for upload in files:
        rel_path = _normalize_upload_path(upload.filename or "")
        rel_text = rel_path.as_posix()
        if rel_text in seen:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Duplicate uploaded relative path '{rel_text}' is not allowed.",
            )
        seen.add(rel_text)
        hasher = sha256()
        size_bytes = 0
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            size_bytes += len(chunk)
            hasher.update(chunk)
        upload.file.seek(0)
        manifest_seed.append(
            {
                "relative_path": rel_text,
                "sha256": hasher.hexdigest(),
                "size_bytes": size_bytes,
            }
        )
    return _deterministic_source_pack_id(manifest_seed)


def stage_source_pack_uploads(files: list[UploadFile]) -> dict[str, Any]:
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select at least one file from a source-pack folder before uploading.",
        )

    source_pack_id = _source_pack_id_for_uploads(files)
    raw_root = _raw_dir(source_pack_id)
    raw_root.mkdir(parents=True, exist_ok=True)
    try:
        for upload in files:
            rel_path = _normalize_upload_path(upload.filename or "")
            destination = raw_root.joinpath(*rel_path.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("wb") as handle:
                shutil.copyfileobj(upload.file, handle)
            upload.file.seek(0)
    finally:
        for upload in files:
            upload.file.close()
    return _payload_for(source_pack_id, raw_root, source_kind="browser_upload")


def validate_source_pack(source_pack_id: str) -> dict[str, Any]:
    if not source_pack_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source-pack validation requires a source_pack_id.",
        )
    raw_root = _raw_dir(source_pack_id)
    if not raw_root.exists() or not raw_root.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source pack '{source_pack_id}' was not found.",
        )
    return _payload_for(source_pack_id, raw_root, source_kind="validated")


def confirm_source_pack_mapping(
    source_pack_id: str,
    relative_path: str,
    *,
    role: str | None = None,
    column_mapping: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload = validate_source_pack(source_pack_id)
    manifest = {str(item.get("relative_path")): item for item in payload.get("manifest", [])}
    item = manifest.get(relative_path)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source '{relative_path}' was not found in source pack '{source_pack_id}'.",
        )
    classification = item.get("classification") or {}
    proposed = classification.get("column_mapping_proposal") or {}
    selected_role = str(role or classification.get("role") or proposed.get("role") or "")
    if selected_role not in TABULAR_ROLE_SIGNATURES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mapping confirmation requires a supported structured target role.",
        )
    mapping_payload = column_mapping or proposed.get("column_mapping") or {}
    required_columns = TABULAR_ROLE_SIGNATURES[selected_role]
    missing_required = [column for column in sorted(required_columns) if column not in mapping_payload]
    if missing_required:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmed mapping is missing required canonical columns: " + ", ".join(missing_required) + ".",
        )
    available_source_columns = set((proposed.get("source_columns") or []))
    invalid_sources = [source for source in mapping_payload.values() if available_source_columns and source not in available_source_columns]
    if invalid_sources:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmed mapping referenced unknown source columns: " + ", ".join(sorted(set(map(str, invalid_sources)))) + ".",
        )
    overrides = _load_mapping_overrides(source_pack_id)
    overrides[relative_path] = {
        "role": selected_role,
        "column_mapping": {str(key): str(value) for key, value in mapping_payload.items()},
        "confirmed_at": datetime.now(UTC).isoformat(),
    }
    _save_mapping_overrides(source_pack_id, overrides)
    return validate_source_pack(source_pack_id)


def resolve_source_pack_for_run(source_pack_id: str, *, allow_partial: bool = False) -> dict[str, Any]:
    payload = validate_source_pack(source_pack_id)
    readiness = payload.get("task_readiness") or {}
    manifest_summary = payload.get("manifest_summary") or {}
    supported_count = int(
        manifest_summary.get("supported_file_count")
        or manifest_summary.get("supported_count")
        or 0
    )
    if supported_count <= 0:
        reasons = readiness.get("blocking_reasons") or [
            "No supported files were registered in the staged source pack."
        ]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                " ".join(str(reason) for reason in reasons)
                + " Upload readable finance files before starting a run."
            ),
        )
    if not readiness.get("ready_for_run") and not allow_partial:
        reasons = readiness.get("blocking_reasons") or [
            "The selected source pack is not ready for the current run model."
        ]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=" ".join(str(reason) for reason in reasons),
        )
    # Confidence gate (orthogonal to completeness): a role whose columns only
    # alias-matched is a low-confidence guess. Block the run until the operator
    # confirms it via POST /source-packs/confirm-mapping. Exact/high-confidence
    # roles are never flagged, so they run without friction.
    unconfirmed_roles = readiness.get("unconfirmed_roles") or []
    if unconfirmed_roles:
        labels = ", ".join(ROLE_LABELS.get(str(role), str(role)) for role in unconfirmed_roles)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "These roles were auto-mapped with low confidence and need operator "
                f"confirmation before running: {labels}. Confirm each via "
                "POST /source-packs/confirm-mapping, then start the run."
            ),
        )
    resolution = (
        _build_partial_dataset(source_pack_id, payload)
        if allow_partial and not readiness.get("ready_for_run")
        else {
            "dataset_root": str(payload["normalized_dataset_root"]),
            "run_mode": "full",
            "available_roles": sorted(RUN_MODEL_REQUIRED_ROLES),
            "missing_roles": [],
        }
    )
    normalized_root = Path(str(resolution["dataset_root"]))
    if not normalized_root.exists() or not normalized_root.is_dir():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Source-pack normalization did not produce a runnable dataset root.",
        )
    payload["run_resolution"] = resolution
    return payload
