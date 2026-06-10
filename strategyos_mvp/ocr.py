from __future__ import annotations

import shutil
import subprocess
import tempfile
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import CONFIG


TOOLS_DIR = Path(__file__).resolve().parent / "tools"
MACOS_VISION_SCRIPT = TOOLS_DIR / "macos_vision_ocr.swift"
OCR_CACHE: dict[tuple[str, int], tuple[list[str], dict]] = {}
RUNTIME_DEPENDENCY_SPECS = (
    {
        "key": "ca_certificates",
        "package": "ca-certificates",
        "config_field": "runtime_dep_ca_certificates_version",
        "binary": None,
        "version_command": None,
    },
    {
        "key": "curl",
        "package": "curl",
        "config_field": "runtime_dep_curl_version",
        "binary": "curl",
        "version_command": ["curl", "--version"],
    },
    {
        "key": "pdftoppm",
        "package": "poppler-utils",
        "config_field": "runtime_dep_poppler_utils_version",
        "binary": "pdftoppm",
        "version_command": ["pdftoppm", "-v"],
    },
    {
        "key": "tesseract",
        "package": "tesseract-ocr",
        "config_field": "runtime_dep_tesseract_version",
        "binary": "tesseract",
        "version_command": ["tesseract", "--version"],
    },
    {
        "key": "tesseract_eng",
        "package": "tesseract-ocr-eng",
        "config_field": "runtime_dep_tesseract_eng_version",
        "binary": None,
        "version_command": None,
    },
)


@dataclass
class OcrPageResult:
    page: int
    status: str
    engine: str | None
    text: str
    detail: str


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=15,
    )


def _package_version(package_name: str) -> tuple[str | None, str | None]:
    try:
        completed = _run_command(["dpkg-query", "-W", "-f=${Version}", package_name])
    except Exception as exc:  # pragma: no cover - defensive subprocess guard
        return None, str(exc)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "package missing"
        return None, detail
    return completed.stdout.strip() or None, None


def _binary_version(command: list[str]) -> tuple[str | None, str | None]:
    try:
        completed = _run_command(command)
    except Exception as exc:  # pragma: no cover - defensive subprocess guard
        return None, str(exc)
    output = (completed.stdout.strip() or completed.stderr.strip()).splitlines()
    if completed.returncode != 0:
        detail = "\n".join(output).strip() or "version probe failed"
        return None, detail
    return output[0].strip() if output else None, None


def _tesseract_languages() -> tuple[list[str], str | None]:
    try:
        completed = _run_command(["tesseract", "--list-langs"])
    except Exception as exc:  # pragma: no cover - defensive subprocess guard
        return [], str(exc)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "language probe failed"
        return [], detail
    languages = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if languages and languages[0].lower().startswith("list of available languages"):
        languages = languages[1:]
    return languages, None


def runtime_dependency_status() -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    overall = "ok"
    for spec in RUNTIME_DEPENDENCY_SPECS:
        expected_version = str(getattr(CONFIG, spec["config_field"]))
        installed_version, package_error = _package_version(spec["package"])
        check: dict[str, Any] = {
            "status": "ok",
            "package": spec["package"],
            "expected_version": expected_version,
            "installed_version": installed_version,
        }
        if package_error or installed_version != expected_version:
            check["status"] = "failed"
            check["reason"] = package_error or (
                f"Installed version '{installed_version}' does not match expected '{expected_version}'."
            )
        binary_name = spec["binary"]
        version_command = spec["version_command"]
        if binary_name:
            binary_path = shutil.which(binary_name)
            check["binary"] = binary_name
            check["binary_path"] = binary_path
            if binary_path is None:
                check["status"] = "failed"
                check["reason"] = f"Binary '{binary_name}' is not on PATH."
            elif version_command is not None:
                reported_version, version_error = _binary_version(version_command)
                check["reported_version"] = reported_version
                if version_error:
                    check["status"] = "failed"
                    check["reason"] = version_error
        checks[spec["key"]] = check
        if check["status"] != "ok":
            overall = "failed"

    languages, language_error = _tesseract_languages()
    lang_check = checks["tesseract_eng"]
    lang_check["language"] = "eng"
    lang_check["available_languages"] = languages
    if language_error:
        lang_check["status"] = "failed"
        lang_check["reason"] = language_error
    elif "eng" not in languages:
        lang_check["status"] = "failed"
        lang_check["reason"] = "Tesseract language 'eng' is not available."
    if lang_check["status"] != "ok":
        overall = "failed"

    return {
        "status": overall,
        "requested_ocr_engine": CONFIG.ocr_engine,
        "resolved_ocr_engines": resolve_ocr_engines(requires_pdf_render=True),
        "checks": checks,
    }


def ocr_empty_pdf_pages(pdf_path: Path, pages: list[str]) -> tuple[list[str], dict]:
    cache_key = (str(pdf_path.resolve()), pdf_path.stat().st_mtime_ns)
    if cache_key in OCR_CACHE:
        cached_pages, cached_status = OCR_CACHE[cache_key]
        return list(cached_pages), deepcopy(cached_status)
    empty_pages = [i + 1 for i, text in enumerate(pages) if not text.strip()]
    engines = resolve_ocr_engines(requires_pdf_render=True)
    status = {
        "required": bool(empty_pages),
        "engine": engines[0] if engines else None,
        "fallback_engines": engines[1:],
        "empty_pages": empty_pages,
        "pages": [],
    }
    if not empty_pages:
        OCR_CACHE[cache_key] = (list(pages), deepcopy(status))
        return pages, status
    if not engines:
        status["blocked_reason"] = "No local OCR engine found. Install tesseract with pdftoppm, or run on macOS with Swift Vision available as fallback."
        OCR_CACHE[cache_key] = (list(pages), deepcopy(status))
        return pages, status
    updated = list(pages)
    with tempfile.TemporaryDirectory(prefix="strategyos_ocr_") as tmp:
        tmp_dir = Path(tmp)
        rendered = render_pdf_pages(pdf_path, tmp_dir)
        for page_no in empty_pages:
            image_path = rendered.get(page_no)
            if image_path is None:
                result = OcrPageResult(page_no, "failed", status["engine"], "", "PDF page render missing.")
                page_status = asdict(result)
            else:
                result, attempts = run_ocr_with_fallback(image_path, page_no, engines)
                if result.text.strip():
                    updated[page_no - 1] = result.text
                page_status = asdict(result)
                if len(attempts) > 1:
                    page_status["attempts"] = [asdict(attempt) for attempt in attempts]
            status["pages"].append(page_status)
    OCR_CACHE[cache_key] = (list(updated), deepcopy(status))
    return updated, status


def detect_ocr_engine() -> str | None:
    engines = resolve_ocr_engines()
    return engines[0] if engines else None


def resolve_ocr_engines(*, requires_pdf_render: bool = False) -> list[str]:
    requested = CONFIG.ocr_engine
    if requested in {"none", "off", "disabled"}:
        return []
    engines: list[str] = []
    has_pdftoppm = bool(shutil.which("pdftoppm"))
    has_tesseract = bool(shutil.which("tesseract"))
    has_vision = bool(shutil.which("swift")) and MACOS_VISION_SCRIPT.exists()
    if requested in {"tesseract", "auto"}:
        if has_tesseract and (has_pdftoppm or not requires_pdf_render):
            engines.append("tesseract")
        if has_vision and (has_pdftoppm or not requires_pdf_render):
            engines.append("macos_vision")
        return engines
    if requested in {"macos_vision", "vision"} and has_vision and (has_pdftoppm or not requires_pdf_render):
        return ["macos_vision"]
    return []


def ocr_image_file(image_path: Path) -> dict:
    engines = resolve_ocr_engines()
    status = {
        "required": True,
        "engine": engines[0] if engines else None,
        "fallback_engines": engines[1:],
        "pages": [],
    }
    if not engines:
        status["blocked_reason"] = "No local OCR engine found. Install tesseract, or run on macOS with Swift Vision available as fallback."
        return status
    result, attempts = run_ocr_with_fallback(image_path, 1, engines)
    page_status = asdict(result)
    if len(attempts) > 1:
        page_status["attempts"] = [asdict(attempt) for attempt in attempts]
    status["pages"] = [page_status]
    return status


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


def run_ocr_with_fallback(image_path: Path, page_no: int, engines: list[str]) -> tuple[OcrPageResult, list[OcrPageResult]]:
    attempts: list[OcrPageResult] = []
    for engine in engines:
        if engine == "tesseract":
            result = run_tesseract_ocr(image_path, page_no)
        elif engine == "macos_vision":
            result = run_macos_vision_ocr(image_path, page_no)
        else:
            result = OcrPageResult(page_no, "failed", engine, "", f"Unsupported OCR engine: {engine}")
        attempts.append(result)
        if result.status == "ok":
            return result, attempts
    return attempts[-1], attempts
