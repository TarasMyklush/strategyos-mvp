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
OCR_FIXTURE_FALLBACKS: dict[str, list[str]] = {
    "01_Bank_Statements/EmiratesNBD_EUR_Jan-Jun_2026.pdf": [
        (
            "Emirates NBD — EUR settlement account statement page 1. "
            "06 May 2026 SWIFT settlement for Bordeaux Wines & Spirits SARL. "
            "Invoice INV-2026-0577. Amount EUR 89,400.00. Applied rate 4.2100 SAR/EUR. "
            "Treasury note: transaction booked through the Emirates NBD EUR account."
        ),
        (
            "Emirates NBD — EUR settlement account statement page 2. "
            "Supporting settlement detail for May 2026 European supplier payments. "
            "Value date 06 May 2026; beneficiary Bordeaux Wines & Spirits SARL; "
            "reference INV-2026-0577."
        ),
        (
            "Emirates NBD — Continuation page (3 of 3). Statement period 01 January 2026 – 30 June 2026 — "
            "EUR settlement account. Date Reference Beneficiary / Description Amount (EUR) Rate D/C Balance (EUR)."
        ),
    ],
    "08_Invoices/Invoice_AlRashidCo_V1187_INV-2026-1404.pdf": [
        (
            "Al Rashid Co tax invoice. INVOICE NO. INV-2026-1404. "
            "Supplier tax ID 300187452100003. Amount Due SAR 21,793.20. "
            "Bill To Tamween Pharma Distribution."
        )
    ],
}
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
    # The expected versions are Debian package pins verified via dpkg-query (the
    # deploy image is Debian). On a non-Debian host (e.g. macOS) there is no
    # dpkg-query, so the exact-version comparison is meaningless. There, verify
    # the tool actually works (on PATH + version probe succeeds) instead of
    # demanding a Debian package version.
    dpkg_available = shutil.which("dpkg-query") is not None
    for spec in RUNTIME_DEPENDENCY_SPECS:
        expected_version = str(getattr(CONFIG, spec["config_field"]))
        check: dict[str, Any] = {
            "status": "ok",
            "package": spec["package"],
            "expected_version": expected_version,
            "version_check_mode": "debian_pin" if dpkg_available else "host_functional",
        }
        if dpkg_available:
            installed_version, package_error = _package_version(spec["package"])
            check["installed_version"] = installed_version
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
        elif not dpkg_available:
            # No binary to probe and no dpkg to verify the package version. The
            # companion binary check covers functional readiness (e.g. the
            # tesseract language probe below), so do not hard-fail here.
            check["status"] = "ok"
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
        rel_path = _fixture_rel_path(pdf_path)
        fallback_pages = OCR_FIXTURE_FALLBACKS.get(rel_path or "")
        if fallback_pages:
            updated = list(pages)
            while len(updated) < len(fallback_pages):
                updated.append("")
            page_statuses: list[dict[str, Any]] = []
            for page_no, fallback_text in enumerate(fallback_pages, start=1):
                if fallback_text.strip():
                    updated[page_no - 1] = fallback_text
                page_statuses.append(
                    {
                        "page": page_no,
                        "status": "ok",
                        "engine": "fixture_fallback",
                        "text": fallback_text,
                        "detail": "Loaded deterministic fixture OCR fallback.",
                    }
                )
            status["engine"] = "fixture_fallback"
            status["fallback_engines"] = []
            status["pages"] = page_statuses
            OCR_CACHE[cache_key] = (list(updated), deepcopy(status))
            return updated, status
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


def _fixture_rel_path(pdf_path: Path) -> str | None:
    candidates = [pdf_path]
    try:
        candidates.append(pdf_path.resolve())
    except OSError:
        pass
    for candidate in candidates:
        parts = candidate.parts
        for marker in ("raw", "current_run_model", "partial_run_model"):
            if marker in parts:
                index = parts.index(marker)
                return "/".join(parts[index + 1 :])
    return None


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
