from dataclasses import replace
from types import SimpleNamespace

from strategyos_mvp import ocr


def test_runtime_dependency_status_is_host_functional_without_dpkg(monkeypatch):
    # On a non-Debian host (no dpkg-query) with working binaries, the runtime
    # check must verify the tools function rather than demand a Debian package
    # version pin it cannot resolve.
    bins = {
        "curl": "/usr/bin/curl",
        "pdftoppm": "/opt/homebrew/bin/pdftoppm",
        "tesseract": "/opt/homebrew/bin/tesseract",
        # dpkg-query intentionally absent
    }
    monkeypatch.setattr(ocr.shutil, "which", lambda name: bins.get(name))
    monkeypatch.setattr(ocr, "_binary_version", lambda cmd: ("tool 1.0", None))
    monkeypatch.setattr(ocr, "_tesseract_languages", lambda: (["eng", "osd"], None))

    status = ocr.runtime_dependency_status()
    assert status["status"] == "ok"
    assert all(c["version_check_mode"] == "host_functional" for c in status["checks"].values())


def test_runtime_dependency_status_fails_when_binary_missing(monkeypatch):
    # Missing tesseract must still fail even in host-functional mode.
    bins = {"curl": "/usr/bin/curl", "pdftoppm": "/opt/homebrew/bin/pdftoppm"}
    monkeypatch.setattr(ocr.shutil, "which", lambda name: bins.get(name))
    monkeypatch.setattr(ocr, "_binary_version", lambda cmd: ("tool 1.0", None))
    monkeypatch.setattr(ocr, "_tesseract_languages", lambda: ([], "tesseract not found"))

    status = ocr.runtime_dependency_status()
    assert status["status"] == "failed"
    assert status["checks"]["tesseract"]["status"] == "failed"


def test_detect_ocr_engine_prefers_tesseract_then_macos_vision(monkeypatch):
    monkeypatch.setattr(ocr, "CONFIG", replace(ocr.CONFIG, ocr_engine="tesseract"))
    monkeypatch.setattr(ocr, "MACOS_VISION_SCRIPT", ocr.Path(__file__))

    def fake_which(name: str) -> str | None:
        mapping = {
            "tesseract": "/usr/local/bin/tesseract",
            "pdftoppm": "/usr/local/bin/pdftoppm",
            "swift": "/usr/bin/swift",
        }
        return mapping.get(name)

    monkeypatch.setattr(ocr.shutil, "which", fake_which)
    assert ocr.resolve_ocr_engines() == ["tesseract", "macos_vision"]
    assert ocr.detect_ocr_engine() == "tesseract"


def test_detect_ocr_engine_falls_back_to_macos_vision_when_tesseract_missing(monkeypatch):
    monkeypatch.setattr(ocr, "CONFIG", replace(ocr.CONFIG, ocr_engine="tesseract"))
    monkeypatch.setattr(ocr, "MACOS_VISION_SCRIPT", ocr.Path(__file__))

    def fake_which(name: str) -> str | None:
        mapping = {
            "pdftoppm": "/usr/local/bin/pdftoppm",
            "swift": "/usr/bin/swift",
        }
        return mapping.get(name)

    monkeypatch.setattr(ocr.shutil, "which", fake_which)
    assert ocr.resolve_ocr_engines() == ["macos_vision"]
    assert ocr.detect_ocr_engine() == "macos_vision"


def test_runtime_dependency_status_reports_pinned_runtime(monkeypatch):
    monkeypatch.setattr(ocr, "CONFIG", replace(ocr.CONFIG, ocr_engine="tesseract"))

    def fake_which(name: str) -> str | None:
        mapping = {
            "curl": "/usr/bin/curl",
            "pdftoppm": "/usr/bin/pdftoppm",
            "tesseract": "/usr/bin/tesseract",
        }
        return mapping.get(name)

    def fake_run(command, check, stdout, stderr, text, timeout):
        joined = tuple(command)
        responses = {
            ("dpkg-query", "-W", "-f=${Version}", "ca-certificates"): (0, "20250419", ""),
            ("dpkg-query", "-W", "-f=${Version}", "curl"): (0, "8.14.1-2+deb13u3", ""),
            ("dpkg-query", "-W", "-f=${Version}", "poppler-utils"): (0, "25.03.0-5+deb13u3", ""),
            ("dpkg-query", "-W", "-f=${Version}", "tesseract-ocr"): (0, "5.5.0-1+b1", ""),
            ("dpkg-query", "-W", "-f=${Version}", "tesseract-ocr-eng"): (0, "1:4.1.0-2", ""),
            ("curl", "--version"): (0, "curl 8.14.1", ""),
            ("pdftoppm", "-v"): (0, "", "pdftoppm version 25.03.0"),
            ("tesseract", "--version"): (0, "tesseract 5.5.0", ""),
            ("tesseract", "--list-langs"): (0, "List of available languages in /usr/share/tesseract-ocr/5/tessdata/\neng\nosd\n", ""),
        }
        returncode, out, err = responses[joined]
        return SimpleNamespace(returncode=returncode, stdout=out, stderr=err)

    monkeypatch.setattr(ocr.shutil, "which", fake_which)
    monkeypatch.setattr(ocr.subprocess, "run", fake_run)

    payload = ocr.runtime_dependency_status()

    assert payload["status"] == "ok"
    assert payload["checks"]["tesseract"]["binary_path"] == "/usr/bin/tesseract"
    assert payload["checks"]["pdftoppm"]["reported_version"] == "pdftoppm version 25.03.0"
    assert payload["checks"]["tesseract_eng"]["language"] == "eng"


def test_runtime_dependency_status_fails_on_version_mismatch(monkeypatch):
    monkeypatch.setattr(ocr, "CONFIG", replace(ocr.CONFIG, ocr_engine="tesseract"))
    monkeypatch.setattr(ocr.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(command, check, stdout, stderr, text, timeout):
        joined = tuple(command)
        if joined == ("dpkg-query", "-W", "-f=${Version}", "tesseract-ocr"):
            return SimpleNamespace(returncode=0, stdout="0.0.0", stderr="")
        if joined[:3] == ("dpkg-query", "-W", "-f=${Version}"):
            versions = {
                "ca-certificates": "20250419",
                "curl": "8.14.1-2+deb13u3",
                "poppler-utils": "25.03.0-5+deb13u3",
                "tesseract-ocr-eng": "1:4.1.0-2",
            }
            return SimpleNamespace(returncode=0, stdout=versions[joined[3]], stderr="")
        if joined == ("tesseract", "--list-langs"):
            return SimpleNamespace(returncode=0, stdout="eng\n", stderr="")
        versions = {
            ("curl", "--version"): "curl 8.14.1",
            ("pdftoppm", "-v"): "pdftoppm version 25.03.0",
            ("tesseract", "--version"): "tesseract 5.5.0",
        }
        value = versions.get(joined, "")
        return SimpleNamespace(returncode=0, stdout=value, stderr="")

    monkeypatch.setattr(ocr.subprocess, "run", fake_run)

    payload = ocr.runtime_dependency_status()

    assert payload["status"] == "failed"
    assert payload["checks"]["tesseract"]["installed_version"] == "0.0.0"
