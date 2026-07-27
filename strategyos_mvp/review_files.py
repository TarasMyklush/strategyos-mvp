from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import threading
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

import pandas as pd
from fastapi import HTTPException, UploadFile, status

from .config import CONFIG


REVIEW_FILE_EXTENSIONS = {".xlsx", ".docx", ".pptx"}
REVIEW_FILE_MIME_TYPES = {
    ".xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
    },
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
    },
    ".pptx": {
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/octet-stream",
    },
}
OOXML_ROOTS = {".xlsx": "xl/", ".docx": "word/", ".pptx": "ppt/"}
MAX_REVIEW_FILE_BYTES = 25 * 1024 * 1024
REVIEW_FILE_CAP = 8
_VAULT_LOCK = threading.Lock()


def _safe_pack_id(source_pack_id: str) -> str:
    value = str(source_pack_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", value):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The governed file source is unavailable.",
        )
    return value


def _source_pack_root(source_pack_id: str) -> Path:
    pack_id = _safe_pack_id(source_pack_id)
    root = (CONFIG.output_root / "source_packs" / pack_id).resolve()
    expected_root = (CONFIG.output_root / "source_packs").resolve()
    try:
        root.relative_to(expected_root)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The governed file source is unavailable.",
        ) from exc
    return root


def _manifest_entries(source_pack_id: str) -> list[dict[str, Any]]:
    path = _source_pack_root(source_pack_id) / "manifest.json"
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [dict(item) for item in payload if isinstance(item, dict)]


def _normal_header(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _metadata_rows(source_pack_id: str) -> list[dict[str, Any]]:
    """Find the document metadata table by its schema, not by its filename."""
    raw_root = _source_pack_root(source_pack_id) / "raw"
    for workbook in sorted(raw_root.rglob("*.xlsx")):
        try:
            sheets = pd.read_excel(workbook, sheet_name=None, dtype=object)
        except Exception:
            continue
        for frame in sheets.values():
            columns = {_normal_header(column): column for column in frame.columns}
            if not {"filename", "format", "category"}.issubset(columns):
                continue
            rows: list[dict[str, Any]] = []
            for _, record in frame.iterrows():
                item = {
                    key: record.get(original)
                    for key, original in columns.items()
                }
                filename = str(item.get("filename") or "").strip()
                if filename:
                    rows.append(item)
            if rows:
                return rows
    return []


def _context_text(summary: Mapping[str, Any] | None) -> str:
    if not isinstance(summary, Mapping):
        return ""
    bounded = {
        "hero": summary.get("hero"),
        "executive_attention": summary.get("executive_attention"),
        "executive_presentation": summary.get("executive_presentation"),
        "executive_diagnostics": summary.get("executive_diagnostics"),
        "findings": summary.get("findings"),
        "finance_kpis": summary.get("finance_kpis"),
        "signals": summary.get("signals"),
    }
    return json.dumps(bounded, default=str, ensure_ascii=False).lower()


def _terms(value: Any) -> set[str]:
    return {
        term
        for term in re.findall(r"[a-z0-9]+", str(value or "").lower())
        if len(term) >= 4
    }


def _relevance_score(row: Mapping[str, Any], context: str) -> float:
    score = 0.0
    linked_refs = str(
        row.get("linked_findings_refs")
        or row.get("linked_findings_and_refs")
        or ""
    )
    for ref in re.findall(r"[A-Za-z]+-\d+(?:\.\.\d+)?", linked_refs):
        if ref.lower() in context:
            score += 10.0
    for key, weight in (("bu_scope", 4.0), ("tags", 2.0), ("category", 1.0)):
        value = row.get(key)
        if value and str(value).strip().lower() in context:
            score += weight
        score += weight * 0.2 * len(_terms(value) & _terms(context))
    return score


def _date_sort_value(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value or "")


def _source_registry(
    source_pack_id: str,
    *,
    summary: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    manifest = _manifest_entries(source_pack_id)
    by_name: dict[str, list[dict[str, Any]]] = {}
    for entry in manifest:
        rel = str(entry.get("relative_path") or "")
        suffix = Path(rel).suffix.lower()
        if suffix not in REVIEW_FILE_EXTENSIONS:
            continue
        by_name.setdefault(Path(rel).name.casefold(), []).append(entry)

    context = _context_text(summary)
    candidates: list[dict[str, Any]] = []
    for row in _metadata_rows(source_pack_id):
        filename = str(row.get("filename") or "").strip()
        matching = by_name.get(filename.casefold()) or []
        if len(matching) != 1:
            continue
        entry = matching[0]
        score = _relevance_score(row, context)
        candidates.append(
            {
                "id": f"source:{entry.get('source_id')}",
                "filename": filename,
                "type": Path(filename).suffix.lower().lstrip("."),
                "group": str(row.get("category") or "Governed document"),
                "scope": str(row.get("bu_scope") or ""),
                "status": str(row.get("status") or ""),
                "owner": str(row.get("owner") or ""),
                "date": _date_sort_value(row.get("date")),
                "linked_refs": str(
                    row.get("linked_findings_refs")
                    or row.get("linked_findings_and_refs")
                    or ""
                ),
                "provenance": "Governed source pack",
                "relevance_score": round(score, 2),
                "view_url": f"/executive/files/{entry.get('source_id')}?disposition=inline",
                "download_url": f"/executive/files/{entry.get('source_id')}?disposition=attachment",
            }
        )
    relevant = [item for item in candidates if item["relevance_score"] > 0]
    relevant.sort(
        key=lambda item: (item["relevance_score"], item["date"]),
        reverse=True,
    )
    return relevant[:REVIEW_FILE_CAP]


def _tenant_key(tenant_id: str) -> str:
    value = str(tenant_id or CONFIG.tenant_slug).strip() or CONFIG.tenant_slug
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _tenant_vault_root(tenant_id: str) -> Path:
    root = (
        CONFIG.output_root / "ceo_review_files" / _tenant_key(tenant_id)
    ).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _tenant_manifest_path(tenant_id: str) -> Path:
    return _tenant_vault_root(tenant_id) / "manifest.json"


def _load_tenant_manifest(tenant_id: str) -> list[dict[str, Any]]:
    path = _tenant_manifest_path(tenant_id)
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [dict(item) for item in payload if isinstance(item, dict)]


def _save_tenant_manifest(tenant_id: str, items: list[dict[str, Any]]) -> None:
    path = _tenant_manifest_path(tenant_id)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(items, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _uploaded_registry(tenant_id: str) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for item in _load_tenant_manifest(tenant_id):
        filename = str(item.get("filename") or "")
        if not filename:
            continue
        key = filename.casefold()
        if key not in latest or str(item.get("uploaded_at") or "") > str(
            latest[key].get("uploaded_at") or ""
        ):
            latest[key] = item
    return [
        {
            "id": f"upload:{item['id']}",
            "filename": item["filename"],
            "type": item["extension"].lstrip("."),
            "group": item.get("group") or "Uploaded for review",
            "scope": item.get("scope") or "",
            "status": "Uploaded",
            "owner": item.get("uploaded_by") or "",
            "date": item.get("uploaded_at") or "",
            "linked_refs": item.get("linked_refs") or "",
            "provenance": "CEO workspace upload",
            "relevance_score": None,
            "view_url": f"/executive/files/{item['id']}?disposition=inline&origin=upload",
            "download_url": f"/executive/files/{item['id']}?disposition=attachment&origin=upload",
        }
        for item in sorted(
            latest.values(),
            key=lambda value: str(value.get("uploaded_at") or ""),
            reverse=True,
        )
    ]


def build_review_file_registry(
    *,
    source_pack_id: str | None,
    tenant_id: str,
    summary: Mapping[str, Any] | None,
) -> dict[str, Any]:
    source_items = (
        _source_registry(source_pack_id, summary=summary)
        if source_pack_id
        else []
    )
    items = (_uploaded_registry(tenant_id) + source_items)[:REVIEW_FILE_CAP]
    groups: list[dict[str, Any]] = []
    by_group: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_group.setdefault(str(item.get("group") or "Governed document"), []).append(item)
    for label, group_items in by_group.items():
        groups.append({"label": label, "items": group_items})
    return {
        "status": "ok",
        "cap": REVIEW_FILE_CAP,
        "count": len(items),
        "groups": groups,
        "versioning": "Latest file with the same name is shown. Version history is not yet available.",
        "empty_reason": (
            None
            if items
            else "No Office file is relevant to the current governed developments or decisions."
        ),
    }


def resolve_source_review_file(source_pack_id: str, source_id: str) -> Path:
    raw_root = (_source_pack_root(source_pack_id) / "raw").resolve()
    matches = [
        entry
        for entry in _manifest_entries(source_pack_id)
        if str(entry.get("source_id") or "") == str(source_id)
    ]
    if len(matches) != 1:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")
    relative_path = str(matches[0].get("relative_path") or "")
    path = (raw_root / relative_path).resolve()
    try:
        path.relative_to(raw_root)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.") from exc
    if path.suffix.lower() not in REVIEW_FILE_EXTENSIONS or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")
    metadata_names = {
        str(row.get("filename") or "").casefold()
        for row in _metadata_rows(source_pack_id)
    }
    if path.name.casefold() not in metadata_names:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")
    return path


def _validate_ooxml(path: Path, extension: str) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if "[Content_Types].xml" not in names or not any(
                name.startswith(OOXML_ROOTS[extension]) for name in names
            ):
                raise ValueError("OOXML structure mismatch")
            lowered = [name.lower() for name in names]
            if any(
                name.endswith((".exe", ".dll", ".js", ".vbs", ".bat", ".cmd"))
                or name.endswith("vbaproject.bin")
                for name in lowered
            ):
                raise ValueError("active or executable content is not allowed")
    except (zipfile.BadZipFile, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is not a safe, readable Office document.",
        ) from exc


def save_review_file_upload(
    upload: UploadFile,
    *,
    tenant_id: str,
    uploaded_by: str,
    group: str | None = None,
    scope: str | None = None,
    linked_refs: str | None = None,
) -> dict[str, Any]:
    filename = Path(str(upload.filename or "")).name
    extension = Path(filename).suffix.lower()
    if extension not in REVIEW_FILE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .xlsx, .docx and .pptx files can be uploaded for CEO review.",
        )
    content_type = str(upload.content_type or "application/octet-stream").lower()
    if content_type not in REVIEW_FILE_MIME_TYPES[extension]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file type does not match its Office extension.",
        )
    item_id = uuid4().hex
    root = _tenant_vault_root(tenant_id)
    destination = root / f"{item_id}{extension}"
    temporary = root / f".{item_id}.uploading"
    size = 0
    digest = hashlib.sha256()
    try:
        with temporary.open("wb") as handle:
            while True:
                chunk = upload.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_REVIEW_FILE_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="CEO review files are limited to 25 MB.",
                    )
                digest.update(chunk)
                handle.write(chunk)
        _validate_ooxml(temporary, extension)
        os.replace(temporary, destination)
    finally:
        upload.file.close()
        if temporary.exists():
            temporary.unlink()
    item = {
        "id": item_id,
        "filename": filename,
        "extension": extension,
        "group": str(group or "Uploaded for review").strip()[:120],
        "scope": str(scope or "").strip()[:120],
        "linked_refs": str(linked_refs or "").strip()[:500],
        "uploaded_at": datetime.now(UTC).isoformat(),
        "uploaded_by": str(uploaded_by or "Executive"),
        "size_bytes": size,
        "sha256": digest.hexdigest(),
        "storage_name": destination.name,
    }
    with _VAULT_LOCK:
        manifest = _load_tenant_manifest(tenant_id)
        manifest.append(item)
        _save_tenant_manifest(tenant_id, manifest)
    return item


def resolve_uploaded_review_file(tenant_id: str, item_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", str(item_id or "")):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")
    matches = [
        item
        for item in _load_tenant_manifest(tenant_id)
        if str(item.get("id") or "") == item_id
    ]
    if len(matches) != 1:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")
    path = (_tenant_vault_root(tenant_id) / str(matches[0].get("storage_name") or "")).resolve()
    try:
        path.relative_to(_tenant_vault_root(tenant_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.") from exc
    if path.suffix.lower() not in REVIEW_FILE_EXTENSIONS or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")
    return path


def media_type_for(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"
