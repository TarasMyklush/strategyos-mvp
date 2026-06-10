from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import CONFIG
from .poc_acceptance import run_poc_acceptance

ACTIVE_EVIDENCE_DIRNAME = "StrategyOS Active Run Evidence"
FINAL_GATE_REPORT_JSON = "StrategyOS Final Gate Report.json"
FINAL_GATE_REPORT_MD = "StrategyOS Final Gate Report.md"
ACTIVE_EVIDENCE_README = "README.md"
CANONICAL_SET_README = "StrategyOS Canonical Set README.md"
FIXTURE_REGRESSION_TEST_PATHS = (
    "tests/test_acceptance_gates.py",
    "tests/test_poc_acceptance.py",
    "tests/test_final_gate.py",
)
GENERIC_HEALTH_TEST_PATHS = (
    "tests/test_runtime_governance.py",
    "tests/test_governed_review_flow_e2e.py",
    "tests/test_frontend_shell.py",
    "tests/test_api_health.py",
    "tests/test_api_identity_boundary.py",
    "tests/test_api_security_boundary.py",
)


def _check_by_name(checks: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for check in checks:
        if check.get("name") == name:
            return check
    return {"name": name, "passed": False, "detail": "check missing from acceptance report"}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _green_acceptance_run_dirs(current_run_dir: Path) -> list[Path]:
    run_dirs: list[Path] = []
    for candidate in CONFIG.output_root.glob("StrategyOS MVP Run-*"):
        if not candidate.is_dir():
            continue
        if candidate.resolve() == current_run_dir.resolve():
            continue
        report = _load_json(candidate / "StrategyOS POC Acceptance Report.json")
        if report.get("passed") is True:
            run_dirs.append(candidate.resolve())
    return sorted(run_dirs, key=lambda path: (path.stat().st_mtime, path.name))


def _active_evidence_source_run_dir() -> Path | None:
    summary = _load_json(
        CONFIG.output_root / ACTIVE_EVIDENCE_DIRNAME / "run_summary.json"
    )
    run_dir = summary.get("run_dir")
    if not run_dir:
        return None
    return Path(str(run_dir)).expanduser().resolve()


def build_promotion_freshness_warning(current_run_dir: Path) -> dict[str, Any]:
    previous_green_runs = _green_acceptance_run_dirs(current_run_dir)
    newest_previous_green = previous_green_runs[-1] if previous_green_runs else None
    active_run_dir = _active_evidence_source_run_dir()
    warning = None
    if newest_previous_green and active_run_dir != newest_previous_green:
        warning = (
            "A newer green local run existed before this final-gate run and was not "
            "the promoted active evidence pack."
        )
    return {
        "passed": True,
        "warning": warning,
        "active_run_dir": str(active_run_dir) if active_run_dir else None,
        "newest_previous_green_run_dir": (
            str(newest_previous_green) if newest_previous_green else None
        ),
        "current_gate_run_dir": str(current_run_dir.resolve()),
        "detail": warning
        or "Promoted active evidence already matched the newest previous green local run, or no previous green run exists.",
    }


def _run_pytest_suite(*test_paths: str) -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "-q", *test_paths]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    output = (completed.stdout or "") + (completed.stderr or "")
    return {
        "passed": completed.returncode == 0,
        "command": " ".join(command),
        "returncode": completed.returncode,
        "output": output.strip(),
        "tests": list(test_paths),
    }


def _run_fixture_regression_validation(dataset: Path | None = None) -> dict[str, Any]:
    selected_dataset = (dataset or CONFIG.source_dataset).resolve()
    canonical_dataset = CONFIG.source_dataset.resolve()
    if selected_dataset != canonical_dataset:
        return {
            "passed": True,
            "skipped": True,
            "command": "skipped",
            "returncode": 0,
            "output": (
                "Skipped Tamween fixture regression because dataset "
                f"'{selected_dataset}' is not the canonical Tamween dataset '{canonical_dataset}'."
            ),
            "tests": list(FIXTURE_REGRESSION_TEST_PATHS),
        }
    return _run_pytest_suite(*FIXTURE_REGRESSION_TEST_PATHS)


def _run_generic_health_validation() -> dict[str, Any]:
    return _run_pytest_suite(*GENERIC_HEALTH_TEST_PATHS)


def build_final_gate_report(
    *,
    acceptance_payload: dict[str, Any],
    fixture_regression_validation: dict[str, Any],
    generic_health_validation: dict[str, Any],
) -> dict[str, Any]:
    summary = acceptance_payload["summary"]
    acceptance = acceptance_payload["acceptance"]
    checks = acceptance.get("checks", [])
    deliverable_check = _check_by_name(checks, "deliverable_presence")
    citation_check = _check_by_name(checks, "resolved_citations_per_finding")
    citation_resolution_rate_check = _check_by_name(checks, "citation_resolution_rate")
    ocr_check = _check_by_name(checks, "ocr_required_extraction_or_failure_handling")
    ping_pong_check = _check_by_name(checks, "challenged_findings_when_ping_pong_active")
    pattern_check = _check_by_name(checks, "planted_patterns_medium_plus")
    total_check = _check_by_name(checks, "total_recoverable_within_tolerance")

    evidence_chain_passed = all(
        (
            citation_check.get("passed", False),
            citation_resolution_rate_check.get("passed", False),
        )
    )
    phase7_passed = all(
        (
            acceptance.get("passed", False),
            deliverable_check.get("passed", False),
            citation_check.get("passed", False),
            citation_resolution_rate_check.get("passed", False),
            ping_pong_check.get("passed", False),
            pattern_check.get("passed", False),
            total_check.get("passed", False),
            summary.get("deliverables_status") == "complete",
            summary.get("run_outcome") == "completed",
        )
    )
    generic_health_passed = all(
        (
            generic_health_validation.get("passed", False),
            summary.get("status") == "completed",
            summary.get("current_stage") == "writer",
            summary.get("run_outcome") == "completed",
            summary.get("checkpoint_count", 0) >= 6,
        )
    )
    fixture_regression_passed = fixture_regression_validation.get("passed", False)
    final_gate_passed = all(
        (
            acceptance.get("passed", False),
            ocr_check.get("passed", False),
            phase7_passed,
            fixture_regression_passed,
            generic_health_passed,
        )
    )
    promotion_freshness = build_promotion_freshness_warning(
        Path(str(acceptance_payload.get("run_dir") or "."))
    )
    warnings = []
    if promotion_freshness.get("warning"):
        warnings.append(promotion_freshness["warning"])
    return {
        "passed": final_gate_passed,
        "decision": "go" if final_gate_passed else "no-go",
        "baseline": "canonical local acceptance harness + OCR baseline",
        "run_dir": acceptance_payload.get("run_dir"),
        "command": "make final-gate",
        "warnings": warnings,
        "summary": {
            "run_id": summary.get("run_id"),
            "status": summary.get("status"),
            "current_stage": summary.get("current_stage"),
            "run_outcome": summary.get("run_outcome"),
            "deliverables_status": summary.get("deliverables_status"),
            "findings": summary.get("findings"),
            "locked_findings": summary.get("locked_findings"),
            "total_recoverable_sar": summary.get("total_recoverable_sar"),
            "runtime": summary.get("runtime", {}),
            "state_store": summary.get("state_store", {}),
            "neo4j": summary.get("neo4j", {}),
            "qdrant": summary.get("qdrant", {}),
        },
        "phase_status": {
            "baseline_acceptance": {
                "passed": acceptance.get("passed", False),
                "detail": "Canonical POC acceptance harness passed locally.",
            },
            "phase_2_ocr": {
                "passed": ocr_check.get("passed", False),
                "detail": ocr_check.get("detail"),
            },
            "phase_4_evidence_chain": {
                "passed": evidence_chain_passed,
                "detail": (
                    f"{citation_check.get('detail')}; "
                    f"{citation_resolution_rate_check.get('detail')}"
                ),
                "checks": {
                    "resolved_citations_per_finding": citation_check,
                    "citation_resolution_rate": citation_resolution_rate_check,
                },
            },
            "phase_7_task3": {
                "passed": phase7_passed,
                "detail": (
                    "Task 3 local writer-complete path is clean: acceptance green, deliverables present, "
                    "findings locked, and corrected downstream artifacts emitted."
                ),
            },
            "fixture_regression": {
                "passed": fixture_regression_passed,
                "detail": (
                    "Dedicated fixture-regression tests are green for the externalized Tamween answer key "
                    "and final-gate wiring."
                ),
                "validation": fixture_regression_validation,
            },
            "generic_health": {
                "passed": generic_health_passed,
                "detail": (
                    "Runtime/governance cleanup is green when the targeted local validation suite passes "
                    "and the acceptance run completes with stable writer-stage lifecycle metadata."
                ),
                "validation": generic_health_validation,
            },
            "promotion_freshness": promotion_freshness,
            "phase_9_final_gate": {
                "passed": final_gate_passed,
                "detail": (
                    "Local final gate requires canonical acceptance, OCR handling, Phase 7 cleanliness, "
                    "fixture regression, and generic health validation to pass together."
                ),
            },
        },
    }


def render_final_gate_report(report: dict[str, Any]) -> str:
    lines = [
        "# StrategyOS Final Gate Report",
        "",
        f"- Passed: {report['passed']}",
        f"- Decision: {report['decision']}",
        f"- Baseline: {report['baseline']}",
        f"- Run dir: {report['run_dir']}",
        f"- Findings: {report['summary'].get('findings')}",
        f"- Locked findings: {report['summary'].get('locked_findings')}",
        f"- Total recoverable SAR: {report['summary'].get('total_recoverable_sar')}",
        "",
        "## Phase status",
        "",
    ]
    for phase_name, payload in report["phase_status"].items():
        status = "PASS" if payload.get("passed") else "FAIL"
        lines.append(f"- {status} - {phase_name}: {payload.get('detail')}")
    fixture_regression = report["phase_status"]["fixture_regression"]["validation"]
    generic_health = report["phase_status"]["generic_health"]["validation"]
    if report.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        for warning in report["warnings"]:
            lines.append(f"- {warning}")
    lines.extend(
        [
            "",
            "## Fixture regression validation command",
            "",
            f"- Command: `{fixture_regression['command']}`",
            f"- Return code: `{fixture_regression['returncode']}`",
            "",
            "```text",
            fixture_regression.get("output") or "",
            "```",
            "",
            "## Generic health validation command",
            "",
            f"- Command: `{generic_health['command']}`",
            f"- Return code: `{generic_health['returncode']}`",
            "",
            "```text",
            generic_health.get("output") or "",
            "```",
        ]
    )
    return "\n".join(lines)


def save_final_gate_report(report: dict[str, Any], run_dir: Path) -> dict[str, Path]:
    json_path = run_dir / FINAL_GATE_REPORT_JSON
    md_path = run_dir / FINAL_GATE_REPORT_MD
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(render_final_gate_report(report), encoding="utf-8")
    return {"final_gate_report_json": json_path, "final_gate_report_md": md_path}


def promote_active_evidence(run_dir: Path, report: dict[str, Any]) -> Path:
    active_dir = CONFIG.output_root / ACTIVE_EVIDENCE_DIRNAME
    active_dir.mkdir(parents=True, exist_ok=True)
    for child in active_dir.iterdir():
        if child.is_file() or child.is_symlink():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)

    for artifact in sorted(run_dir.iterdir()):
        if artifact.is_file():
            shutil.copy2(artifact, active_dir / artifact.name)

    readme_lines = [
        "# StrategyOS Active Run Evidence",
        "",
        "Date: 2026-06-10",
        "Status: Canonical current local-only evidence set",
        "",
        "## Promoted source pack",
        "",
        "This folder is the promoted artifact pack from the latest local final-gate run at:",
        "",
        f"`{run_dir}`",
        "",
        "## Verification outcome",
        "",
        f"- Final gate passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Findings: `{report['summary'].get('findings')}`",
        f"- Locked findings: `{report['summary'].get('locked_findings')}`",
        f"- Total recoverable SAR: `{report['summary'].get('total_recoverable_sar')}`",
        f"- Phase 7 cleared: `{report['phase_status']['phase_7_task3']['passed']}`",
        f"- Fixture regression cleared: `{report['phase_status']['fixture_regression']['passed']}`",
        f"- Generic health cleared: `{report['phase_status']['generic_health']['passed']}`",
        f"- OCR gate: `{report['phase_status']['phase_2_ocr']['passed']}`",
        f"- Evidence-chain gate: `{report['phase_status']['phase_4_evidence_chain']['passed']}`",
        "",
        "## Canonical artifacts in this folder",
        "",
    ]
    for artifact in sorted(path.name for path in run_dir.iterdir() if path.is_file()):
        readme_lines.append(f"- `{artifact}`")
    readme_lines.extend(
        [
            "",
            "## Truthfulness rule",
            "",
            "This folder must mirror the latest local final-gate run exactly. If a newer local gate run is promoted,",
            "replace this pack wholesale instead of mixing artifacts across runs.",
        ]
    )
    (active_dir / ACTIVE_EVIDENCE_README).write_text(
        "\n".join(readme_lines) + "\n",
        encoding="utf-8",
    )
    return active_dir


def refresh_canonical_set_readme(active_dir: Path, run_dir: Path) -> Path:
    readme_path = CONFIG.output_root / CANONICAL_SET_README
    readme_path.write_text(
        "\n".join(
            [
                "# StrategyOS Canonical Set README",
                "",
                "Date: 2026-06-10",
                "Status: Canonical outputs index after local final-gate refresh",
                "",
                "## Canonical/current set to use now",
                "",
                "1. `StrategyOS Current As-Built Architecture (Canonical).md` — controlling as-built architecture and current open-gap register",
                "2. `StrategyOS Data Management Model.md` — current supporting data model reference",
                "3. `StrategyOS End-User Guides/` — current user/operator/reviewer guides",
                "4. `StrategyOS Agent Input/` — active runtime input pack for deterministic analysis",
                "5. `StrategyOS Evaluation/` — human-only evaluation pack kept outside runtime and optional model review",
                f"6. `{ACTIVE_EVIDENCE_DIRNAME}/` — canonical current run evidence from `{run_dir.name}`",
                "7. `StrategyOS Runtime Proofs/` — targeted runtime proof packs separate from promoted active evidence",
                "8. `Archive/` — historical/stale/transitional items retained for traceability",
                "",
                "## Active run evidence status",
                "",
                f"`{ACTIVE_EVIDENCE_DIRNAME}/` now mirrors the latest local final-gate run at `{run_dir}`.",
                "Trust this folder over older phase-labelled packs when evidence conflicts.",
                "",
                "## Promotion rule",
                "",
                "Canonical evidence numbers may only be quoted from `StrategyOS Active Run Evidence/`.",
                "Promotion happens through `make final-gate`; direct `run_poc` runs are experimental until promoted.",
                "",
                "## Use rule",
                "",
                "If a file outside this canonical set conflicts with one inside it, trust the canonical/current set and",
                "treat the outside file as historical only.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return readme_path


def run_local_final_gate(
    *,
    promote_evidence: bool = True,
    dataset: Path | None = None,
    run_dir: Path | None = None,
) -> dict[str, Any]:
    acceptance_payload = run_poc_acceptance(dataset=dataset or CONFIG.source_dataset, run_dir=run_dir or CONFIG.default_run_dir)
    fixture_regression_validation = _run_fixture_regression_validation(dataset or CONFIG.source_dataset)
    generic_health_validation = _run_generic_health_validation()
    report = build_final_gate_report(
        acceptance_payload=acceptance_payload,
        fixture_regression_validation=fixture_regression_validation,
        generic_health_validation=generic_health_validation,
    )
    actual_run_dir = Path(acceptance_payload["run_dir"])
    final_gate_artifacts = save_final_gate_report(report, actual_run_dir)
    summary_path = actual_run_dir / "run_summary.json"
    summary = acceptance_payload["summary"]
    summary_artifacts = dict(summary.get("artifacts", {}))
    summary_artifacts.update({key: str(path) for key, path in final_gate_artifacts.items()})
    summary["artifacts"] = summary_artifacts
    summary["final_gate"] = report
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    active_dir = None
    canonical_readme = None
    if promote_evidence:
        active_dir = promote_active_evidence(actual_run_dir, report)
        canonical_readme = refresh_canonical_set_readme(active_dir, actual_run_dir)
    return {
        "passed": report["passed"],
        "decision": report["decision"],
        "run_dir": str(actual_run_dir),
        "report": report,
        "artifacts": {key: str(path) for key, path in final_gate_artifacts.items()},
        "active_evidence_dir": str(active_dir) if active_dir else None,
        "canonical_set_readme": str(canonical_readme) if canonical_readme else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local StrategyOS final gate.")
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument(
        "--no-promote-evidence",
        action="store_true",
        help="Do not refresh the canonical active evidence pack after the run.",
    )
    args = parser.parse_args()
    payload = run_local_final_gate(
        promote_evidence=not args.no_promote_evidence,
        dataset=args.dataset,
        run_dir=args.run_dir,
    )
    print(json.dumps(payload, indent=2))
    if not payload["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
