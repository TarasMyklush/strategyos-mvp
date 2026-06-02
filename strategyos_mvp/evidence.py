from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from pypdf import PdfReader

from .models import Citation
from .ocr import ocr_empty_pdf_pages


IGNORED_NAMES = {".DS_Store"}


@dataclass
class EvidenceStore:
    dataset_root: Path
    manifest: dict[str, dict]
    pdf_text: dict[str, list[str]]
    ocr_status: dict[str, dict]

    @classmethod
    def build(cls, dataset_root: Path) -> "EvidenceStore":
        manifest: dict[str, dict] = {}
        pdf_text: dict[str, list[str]] = {}
        ocr_status: dict[str, dict] = {}
        ingested_at = datetime.now(UTC).isoformat()
        for path in iter_source_files(dataset_root):
            rel = str(path.relative_to(dataset_root))
            digest = sha256_file(path)
            manifest[rel] = {
                "path": rel,
                "size_bytes": path.stat().st_size,
                "sha256": digest,
                "source_group": path.parent.name,
                "ingested_at": ingested_at,
            }
            if path.suffix.lower() == ".pdf":
                pages = extract_pdf_pages(path)
                pages, status = ocr_empty_pdf_pages(path, pages)
                pdf_text[rel] = pages
                if status["required"]:
                    ocr_status[rel] = status
        return cls(dataset_root=dataset_root, manifest=manifest, pdf_text=pdf_text, ocr_status=ocr_status)

    def hash_for(self, rel_path: str) -> str | None:
        return self.manifest.get(rel_path, {}).get("sha256")

    def citation(self, rel_path: str, locator: str, excerpt: str = "") -> Citation:
        return Citation(
            source_path=rel_path,
            locator=locator,
            excerpt=excerpt[:500],
            source_hash=self.hash_for(rel_path),
        )

    def pdf_excerpt(self, rel_path: str, terms: Iterable[str], max_chars: int = 360) -> str:
        pages = self.pdf_text.get(rel_path, [])
        lowered_terms = [t.lower() for t in terms if t]
        for page_no, text in enumerate(pages, start=1):
            low = text.lower()
            if all(term in low for term in lowered_terms):
                compact = " ".join(text.split())
                return f"page {page_no}: {compact[:max_chars]}"
        return ""

    def save_manifest(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(self.manifest, indent=2), encoding="utf-8")


def iter_source_files(dataset_root: Path) -> list[Path]:
    return sorted(
        p
        for p in dataset_root.rglob("*")
        if p.is_file() and p.name not in IGNORED_NAMES and not p.name.startswith(".")
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_pdf_pages(path: Path) -> list[str]:
    try:
        reader = PdfReader(str(path))
        return [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:  # pragma: no cover - defensive extraction guard
        return [f"[PDF extraction failed: {exc}]"]


def row_locator(row_index: int, header_row: int = 1) -> str:
    return f"Excel row {row_index + header_row + 1}"
