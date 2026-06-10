from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .citation_resolver import resolve_findings
from .ingestion import DataBundle
from .models import AuditEvent, Finding
from .paths import DEFAULT_RUN_DIR, SOURCE_DATASET
from .quality import build_data_quality_report
from .run_poc import _execute_strategyos_workflow

ANSWER_KEY_PATH = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "tamween_answer_key.json"
TOTAL_RECOVERABLE_TOLERANCE_SAR = 0.01
MINIMUM_RESOLVED_CITATIONS_PER_FINDING = 3
MINIMUM_CHALLENGED_FINDINGS = 4
REQUIRED_DELIVERABLE_KEYS = {
    "case_file",
    "case_file_pdf",
    "working_capital",
    "qa",
    "audit_log",
    "data_quality_json",
    "data_quality_md",
    "citation_audit",
    "knowledge_graph",
    "manifest",
}


def load_tamween_answer_key(answer_key_path: Path = ANSWER_KEY_PATH) -> dict[str, Any]:
    payload = json.loads(answer_key_path.read_text(encoding="utf-8"))
    return {
        "expected_pattern_types": set(payload["expected_pattern_types"]),
        "expected_total_recoverable_sar": float(payload["expected_total_recoverable_sar"]),
        "answer_key_path": str(answer_key_path),
    }


def _confidence_rank(confidence: str) -> int:
    return {"LOW": 1, "MEDIUM": 2, "HIGH": 3}.get(str(confidence).upper(), 0)


def evaluate_poc_acceptance(
    *,
    summary: dict[str, Any],
    findings: list[Finding],
    bundle: DataBundle,
    audit_events: list[AuditEvent],
    tolerance_sar: float = TOTAL_RECOVERABLE_TOLERANCE_SAR,
    answer_key: dict[str, Any] | None = None,
) -> dict[str, Any]:
    expectations = answer_key or load_tamween_answer_key()
    expected_pattern_types = expectations["expected_pattern_types"]
    expected_total_recoverable_sar = expectations["expected_total_recoverable_sar"]

    findings_by_pattern = {finding.pattern_type: finding for finding in findings}
    resolved_citations = resolve_findings(bundle, findings)
    resolved_counts: Counter[str] = Counter(
        item["finding_id"] for item in resolved_citations if item.get("resolved")
    )
    findings_below_medium = sorted(
        finding.finding_id
        for finding in findings
        if _confidence_rank(finding.confidence) < _confidence_rank("MEDIUM")
    )
    missing_patterns = sorted(expected_pattern_types - set(findings_by_pattern))
    pattern_check = {
        "name": "planted_patterns_medium_plus",
        "passed": not missing_patterns and not findings_below_medium and len(findings) >= 8,
        "detail": (
            f"expected_patterns={len(expected_pattern_types)} observed={len(findings_by_pattern)} "
            f"missing={missing_patterns or 'none'} below_medium={findings_below_medium or 'none'}"
        ),
    }

    total_recoverable = round(float(summary.get("total_recoverable_sar") or 0.0), 2)
    recoverable_delta = round(total_recoverable - expected_total_recoverable_sar, 2)
    total_recoverable_check = {
        "name": "total_recoverable_within_tolerance",
        "passed": abs(recoverable_delta) <= tolerance_sar,
        "detail": (
            f"expected={expected_total_recoverable_sar:.2f} actual={total_recoverable:.2f} "
            f"delta={recoverable_delta:.2f} tolerance={tolerance_sar:.2f}"
        ),
    }

    citation_failures = [
        {
            "finding_id": finding.finding_id,
            "resolved_citations": resolved_counts[finding.finding_id],
            "required": MINIMUM_RESOLVED_CITATIONS_PER_FINDING,
        }
        for finding in findings
        if resolved_counts[finding.finding_id] < MINIMUM_RESOLVED_CITATIONS_PER_FINDING
    ]
    citation_check = {
        "name": "resolved_citations_per_finding",
        "passed": not citation_failures,
        "detail": (
            "all findings resolved at least three citations"
            if not citation_failures
            else f"failures={citation_failures}"
        ),
    }

    challenged_finding_ids = sorted(
        {
            event.finding_id
            for event in audit_events
            if event.actor == "Finance Auditor" and event.action == "challenge"
        }
    )
    ping_pong_active = bool(audit_events)
    challenge_check = {
        "name": "challenged_findings_when_ping_pong_active",
        "passed": (not ping_pong_active)
        or len(challenged_finding_ids) >= MINIMUM_CHALLENGED_FINDINGS,
        "detail": (
            f"ping_pong_active={ping_pong_active} challenged={len(challenged_finding_ids)} "
            f"required={MINIMUM_CHALLENGED_FINDINGS} ids={challenged_finding_ids}"
        ),
    }

    artifacts = summary.get("artifacts", {}) or {}
    missing_deliverables = sorted(
        key
        for key in REQUIRED_DELIVERABLE_KEYS
        if not artifacts.get(key) or not Path(str(artifacts[key])).exists()
    )
    deliverable_check = {
        "name": "deliverable_presence",
        "passed": not missing_deliverables,
        "detail": (
            "all required deliverables are present"
            if not missing_deliverables
            else f"missing={missing_deliverables}"
        ),
    }

    quality_report = build_data_quality_report(bundle, findings)
    ocr_failures: list[dict[str, Any]] = []
    for source in quality_report["pdf_sources"]:
        ocr_status = source.get("ocr_status") or {}
        verification = source.get("verification") or {}
        unresolved_pages = [
            page for page in ocr_status.get("pages", []) if page.get("status") != "ok"
        ]
        surfaced_issue = any(
            issue.get("source") == source["source_path"]
            and "ocr" in str(issue.get("detail", "")).lower()
            for issue in quality_report["quality_issues"]
        )
        requires_ocr_handling = bool(ocr_status.get("required") or source.get("needs_ocr"))
        if not requires_ocr_handling:
            continue
        handled = (
            (source.get("ocr_used") and bool(verification.get("verified")))
            or bool(ocr_status.get("blocked_reason"))
            or bool(unresolved_pages)
            or surfaced_issue
        )
        if not handled:
            ocr_failures.append(
                {
                    "source_path": source["source_path"],
                    "needs_ocr": source.get("needs_ocr"),
                    "ocr_used": source.get("ocr_used"),
                    "verification": verification,
                }
            )
    ocr_check = {
        "name": "ocr_required_extraction_or_failure_handling",
        "passed": not ocr_failures,
        "detail": (
            "all OCR-required sources were extracted or surfaced as failures"
            if not ocr_failures
            else f"failures={ocr_failures}"
        ),
    }

    checks = [
        pattern_check,
        total_recoverable_check,
        citation_check,
        challenge_check,
        deliverable_check,
        ocr_check,
    ]
    finding_summaries = []
    for finding in findings:
        finding_summaries.append(
            {
                "finding_id": finding.finding_id,
                "pattern_type": finding.pattern_type,
                "confidence": finding.confidence,
                "recoverable_sar": finding.recoverable_sar,
                "resolved_citations": resolved_counts[finding.finding_id],
            }
        )
    return {
        "passed": all(check["passed"] for check in checks),
        "run_id": summary.get("run_id"),
        "run_dir": summary.get("run_dir"),
        "answer_key_path": expectations.get("answer_key_path"),
        "expected_total_recoverable_sar": expected_total_recoverable_sar,
        "actual_total_recoverable_sar": total_recoverable,
        "checks": checks,
        "findings": finding_summaries,
        "quality_report_status": quality_report["status"],
    }


def save_acceptance_report(report: dict[str, Any], run_dir: Path) -> dict[str, Path]:
    run_dir.mkdir(parents=True, exist_ok=True)
    json_path = run_dir / "StrategyOS POC Acceptance Report.json"
    md_path = run_dir / "StrategyOS POC Acceptance Report.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(render_acceptance_report(report), encoding="utf-8")
    return {"acceptance_report_json": json_path, "acceptance_report_md": md_path}


def render_acceptance_report(report: dict[str, Any]) -> str:
    lines = [
        "# StrategyOS POC Acceptance Report",
        "",
        f"- Passed: {report['passed']}",
        f"- Run ID: {report.get('run_id')}",
        f"- Run dir: {report.get('run_dir')}",
        f"- Recoverable SAR: {report['actual_total_recoverable_sar']:.2f}",
        f"- Data quality status: {report.get('quality_report_status')}",
        "",
        "## Checks",
        "",
    ]
    for check in report["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        lines.append(f"- {status} - {check['name']}: {check['detail']}")
    lines.extend(["", "## Findings", ""])
    for finding in report["findings"]:
        lines.append(
            f"- {finding['finding_id']} ({finding['pattern_type']}): confidence={finding['confidence']} "
            f"recoverable_sar={finding['recoverable_sar']:.2f} resolved_citations={finding['resolved_citations']}"
        )
    return "\n".join(lines)


def run_poc_acceptance(
    *,
    dataset: Path = SOURCE_DATASET,
    run_dir: Path = DEFAULT_RUN_DIR,
    tolerance_sar: float = TOTAL_RECOVERABLE_TOLERANCE_SAR,
    sync_artifacts: bool = False,
) -> dict[str, Any]:
    summary, result = _execute_strategyos_workflow(
        dataset=dataset,
        run_dir=run_dir,
        skip_prepare=True,
        sync_artifacts=sync_artifacts,
        local_only_fallback=True,
        require_human_review=False,
    )
    report = evaluate_poc_acceptance(
        summary=summary,
        findings=result.get("findings", []),
        bundle=result["bundle"],
        audit_events=result.get("audit_events", []),
        tolerance_sar=tolerance_sar,
    )
    run_path = Path(str(summary["run_dir"]))
    acceptance_artifacts = save_acceptance_report(report, run_path)
    summary_artifacts = dict(summary.get("artifacts", {}))
    summary_artifacts.update(
        {key: str(path) for key, path in acceptance_artifacts.items()}
    )
    summary["artifacts"] = summary_artifacts
    summary["acceptance"] = report
    (run_path / "run_summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    return {
        "passed": report["passed"],
        "run_dir": str(run_path),
        "command": "make poc-acceptance",
        "summary": summary,
        "acceptance": report,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the canonical StrategyOS POC acceptance harness."
    )
    parser.add_argument("--dataset", type=Path, default=SOURCE_DATASET)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument(
        "--tolerance-sar",
        type=float,
        default=TOTAL_RECOVERABLE_TOLERANCE_SAR,
        help="Allowed absolute drift for total recoverable SAR.",
    )
    parser.add_argument(
        "--sync-artifacts",
        action="store_true",
        help="Upload artifacts to the configured object store after the run.",
    )
    args = parser.parse_args()
    payload = run_poc_acceptance(
        dataset=args.dataset,
        run_dir=args.run_dir,
        tolerance_sar=args.tolerance_sar,
        sync_artifacts=args.sync_artifacts,
    )
    print(json.dumps(payload, indent=2))
    if not payload["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
