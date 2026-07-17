from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from pypdf import PdfReader

from .file_traversal import iter_files
from .models import Citation
from .ocr import ocr_empty_pdf_pages
from .prompt_injection import guard_untrusted_document_text
from .source_governance import is_agent_evidence_path


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

    # Evidence-content budget per citation excerpt. The prompt-injection guard
    # wrapper (prefix + markers) is added on top of this and must NOT count
    # against it, otherwise the wrapper evicts the actual evidence text.
    EXCERPT_EVIDENCE_BUDGET = 500

    def citation(self, rel_path: str, locator: str, excerpt: str = "") -> Citation:
        if "BEGIN_UNTRUSTED_EVIDENCE" in excerpt:
            # Already wrapped upstream (e.g. by pdf_excerpt); the inner evidence
            # was already bounded there. Keep it intact rather than truncating
            # through the guard wrapper.
            guarded_excerpt = excerpt
        else:
            guarded_excerpt = guard_untrusted_document_text(
                excerpt,
                source_name=rel_path,
                max_chars=self.EXCERPT_EVIDENCE_BUDGET,
            )["guarded_text"]
        return Citation(
            source_path=rel_path,
            locator=locator,
            excerpt=guarded_excerpt,
            source_hash=self.hash_for(rel_path),
        )

    def pdf_excerpt(self, rel_path: str, terms: Iterable[str], max_chars: int = 360) -> str:
        pages = self.pdf_text.get(rel_path, [])
        lowered_terms = [t.lower() for t in terms if t]
        for page_no, text in enumerate(pages, start=1):
            low = text.lower()
            if all(term in low for term in lowered_terms):
                compact = " ".join(text.split())
                compact_low = compact.lower()
                anchor_positions = [compact_low.find(term) for term in lowered_terms if term in compact_low]
                anchor = max(anchor_positions) if anchor_positions else 0
                start = max(anchor - 220, 0)
                excerpt = f"page {page_no}: {compact[start:start + max_chars]}"
                return guard_untrusted_document_text(
                    excerpt,
                    source_name=rel_path,
                    max_chars=max_chars,
                )["guarded_text"]
        return ""

    def save_manifest(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(self.manifest, indent=2), encoding="utf-8")


def iter_source_files(dataset_root: Path) -> list[Path]:
    return [
        path
        for path in iter_files(dataset_root, ignored_names=IGNORED_NAMES)
        if is_agent_evidence_path(path.relative_to(dataset_root).as_posix())
    ]


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


def page_locator(page_number: int, label: str = "PDF page") -> str:
    return f"{label} page {page_number}"
