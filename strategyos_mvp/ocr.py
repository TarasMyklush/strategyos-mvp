from __future__ import annotations

import shutil
import subprocess
import tempfile
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import CONFIG


TOOLS_DIR = Path(__file__).resolve().parent / "tools"
MACOS_VISION_SCRIPT = TOOLS_DIR / "macos_vision_ocr.swift"
OCR_CACHE: dict[tuple[str, int], tuple[list[str], dict]] = {}


@dataclass
class OcrPageResult:
    page: int
    status: str
    engine: str | None
    text: str
    detail: str


def ocr_empty_pdf_pages(pdf_path: Path, pages: list[str]) -> tuple[list[str], dict]:
    cache_key = (str(pdf_path.resolve()), pdf_path.stat().st_mtime_ns)
    if cache_key in OCR_CACHE:
        cached_pages, cached_status = OCR_CACHE[cache_key]
        return list(cached_pages), deepcopy(cached_status)
    empty_pages = [i + 1 for i, text in enumerate(pages) if not text.strip()]
    status = {
        "required": bool(empty_pages),
        "engine": detect_ocr_engine(),
        "empty_pages": empty_pages,
        "pages": [],
    }
    if not empty_pages:
        OCR_CACHE[cache_key] = (list(pages), deepcopy(status))
        return pages, status
    if status["engine"] is None:
        status["blocked_reason"] = "No local OCR engine found. Install tesseract/ocrmypdf or run on macOS with Swift Vision available."
        OCR_CACHE[cache_key] = (list(pages), deepcopy(status))
        return pages, status
    if status["engine"] == "macos_vision":
        updated = list(pages)
        with tempfile.TemporaryDirectory(prefix="strategyos_ocr_") as tmp:
            tmp_dir = Path(tmp)
            rendered = render_pdf_pages(pdf_path, tmp_dir)
            for page_no in empty_pages:
                image_path = rendered.get(page_no)
                if image_path is None:
                    result = OcrPageResult(page_no, "failed", "macos_vision", "", "PDF page render missing.")
                else:
                    result = run_macos_vision_ocr(image_path, page_no)
                    if result.text.strip():
                        updated[page_no - 1] = result.text
                status["pages"].append(asdict(result))
        OCR_CACHE[cache_key] = (list(updated), deepcopy(status))
        return updated, status
    if status["engine"] == "tesseract":
        updated = list(pages)
        with tempfile.TemporaryDirectory(prefix="strategyos_ocr_") as tmp:
            tmp_dir = Path(tmp)
            rendered = render_pdf_pages(pdf_path, tmp_dir)
            for page_no in empty_pages:
                image_path = rendered.get(page_no)
                if image_path is None:
                    result = OcrPageResult(page_no, "failed", "tesseract", "", "PDF page render missing.")
                else:
                    result = run_tesseract_ocr(image_path, page_no)
                    if result.text.strip():
                        updated[page_no - 1] = result.text
                status["pages"].append(asdict(result))
        OCR_CACHE[cache_key] = (list(updated), deepcopy(status))
        return updated, status
    status["blocked_reason"] = f"Unsupported OCR engine: {status['engine']}"
    OCR_CACHE[cache_key] = (list(pages), deepcopy(status))
    return pages, status


def detect_ocr_engine() -> str | None:
    requested = CONFIG.ocr_engine
    if requested in {"none", "off", "disabled"}:
        return None
    if requested in {"tesseract", "auto"} and shutil.which("tesseract") and shutil.which("pdftoppm"):
        return "tesseract"
    if requested in {"macos_vision", "vision", "auto"} and shutil.which("swift") and shutil.which("pdftoppm") and MACOS_VISION_SCRIPT.exists():
        return "macos_vision"
    if requested in {"ocrmypdf", "auto"} and shutil.which("ocrmypdf"):
        return "ocrmypdf"
    return None


def render_pdf_pages(pdf_path: Path, tmp_dir: Path) -> dict[int, Path]:
    prefix = tmp_dir / "page"
    subprocess.run(
        ["pdftoppm", "-png", "-r", "220", str(pdf_path), str(prefix)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    rendered: dict[int, Path] = {}
    for path in sorted(tmp_dir.glob("page-*.png")):
        page_no = int(path.stem.split("-")[-1])
        rendered[page_no] = path
    return rendered


def run_macos_vision_ocr(image_path: Path, page_no: int) -> OcrPageResult:
    module_cache = Path(tempfile.gettempdir()) / "strategyos_swift_module_cache"
    module_cache.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            ["swift", "-module-cache-path", str(module_cache), str(MACOS_VISION_SCRIPT), str(image_path)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
        )
    except Exception as exc:  # pragma: no cover - defensive subprocess guard
        return OcrPageResult(page_no, "failed", "macos_vision", "", str(exc))
    text = completed.stdout.strip()
    if completed.returncode != 0:
        return OcrPageResult(page_no, "failed", "macos_vision", text, completed.stderr.strip())
    return OcrPageResult(page_no, "ok" if text else "empty", "macos_vision", text, completed.stderr.strip())


def run_tesseract_ocr(image_path: Path, page_no: int) -> OcrPageResult:
    try:
        completed = subprocess.run(
            ["tesseract", str(image_path), "stdout", "-l", "eng", "--psm", "6"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=90,
        )
    except Exception as exc:  # pragma: no cover - defensive subprocess guard
        return OcrPageResult(page_no, "failed", "tesseract", "", str(exc))
    text = completed.stdout.strip()
    if completed.returncode != 0:
        return OcrPageResult(page_no, "failed", "tesseract", text, completed.stderr.strip())
    return OcrPageResult(page_no, "ok" if text else "empty", "tesseract", text, completed.stderr.strip())
