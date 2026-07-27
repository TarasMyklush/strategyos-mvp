from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

from fastapi import UploadFile
from openpyxl import Workbook
import pytest

from strategyos_mvp import review_files


def _ooxml_bytes(root: str) -> bytes:
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr(f"{root}/document.xml", "<document />")
    return stream.getvalue()


def _build_source_pack(tmp_path: Path) -> tuple[str, str]:
    pack_id = "pack_12345678"
    raw = tmp_path / "source_packs" / pack_id / "raw"
    raw.mkdir(parents=True)
    document = raw / "Governed_Operating_Cost_Decision.pptx"
    document.write_bytes(_ooxml_bytes("ppt"))

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(
        [
            "Filename",
            "Format",
            "Category",
            "BU / Scope",
            "Linked findings & refs",
            "Status",
            "Owner",
            "Date",
            "Tags",
        ]
    )
    sheet.append(
        [
            document.name,
            "Presentation",
            "Decision pack",
            "Distribution",
            "SIG-2026-07",
            "Final",
            "BU Finance",
            "2026-06-17",
            "operating cost",
        ]
    )
    workbook.save(raw / "Metadata.xlsx")
    source_id = "source-opaque-1"
    manifest = [
        {
            "relative_path": document.name,
            "source_id": source_id,
            "size_bytes": document.stat().st_size,
        },
        {
            "relative_path": "Metadata.xlsx",
            "source_id": "source-metadata",
            "size_bytes": (raw / "Metadata.xlsx").stat().st_size,
        },
    ]
    (tmp_path / "source_packs" / pack_id / "manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return pack_id, source_id


def test_review_registry_is_schema_driven_relevance_selected_and_resolvable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        review_files,
        "CONFIG",
        SimpleNamespace(output_root=tmp_path, tenant_slug="test"),
    )
    pack_id, source_id = _build_source_pack(tmp_path)

    registry = review_files.build_review_file_registry(
        source_pack_id=pack_id,
        tenant_id="tenant-a",
        summary={"signals": [{"signal_id": "SIG-2026-07"}]},
    )

    assert registry["cap"] == review_files.REVIEW_FILE_CAP
    assert registry["count"] == 1
    item = registry["groups"][0]["items"][0]
    assert item["group"] == "Decision pack"
    assert item["relevance_score"] > 0
    assert review_files.resolve_source_review_file(pack_id, source_id).name == item["filename"]


def test_uploaded_office_file_is_tenant_scoped_and_latest_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        review_files,
        "CONFIG",
        SimpleNamespace(output_root=tmp_path, tenant_slug="test"),
    )
    upload = UploadFile(
        filename="CEO_Decision.docx",
        file=BytesIO(_ooxml_bytes("word")),
    )
    upload.headers = {"content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    item = review_files.save_review_file_upload(
        upload,
        tenant_id="tenant-a",
        uploaded_by="CEO",
        group="Decision brief",
    )

    assert review_files.resolve_uploaded_review_file("tenant-a", item["id"]).is_file()
    with pytest.raises(Exception):
        review_files.resolve_uploaded_review_file("tenant-b", item["id"])

    registry = review_files.build_review_file_registry(
        source_pack_id=None,
        tenant_id="tenant-a",
        summary={},
    )
    assert registry["count"] == 1
    assert registry["groups"][0]["label"] == "Decision brief"


def test_upload_rejects_non_office_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        review_files,
        "CONFIG",
        SimpleNamespace(output_root=tmp_path, tenant_slug="test"),
    )
    upload = UploadFile(filename="payload.exe", file=BytesIO(b"MZ"))
    upload.headers = {"content-type": "application/octet-stream"}
    with pytest.raises(Exception):
        review_files.save_review_file_upload(
            upload,
            tenant_id="tenant-a",
            uploaded_by="CEO",
        )
