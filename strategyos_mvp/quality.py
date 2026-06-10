from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .citation_resolver import resolve_findings, validate_quantitative_claims
from .ingestion import DataBundle
from .ingestion import OCR_REQUIRED_VERIFICATIONS
from .models import Finding

MINIMUM_RESOLVED_CITATIONS_PER_FINDING = 3


def build_data_quality_report(bundle: DataBundle, findings: list[Finding]) -> dict[str, Any]:
    structured_sources = structured_source_summary(bundle)
    pdf_sources = pdf_source_summary(bundle)
    citation_records = resolve_findings(bundle, findings)
    quantitative_claims = validate_quantitative_claims(bundle, findings)
    critical_count = sum(1 for issue in bundle.quality_issues if issue.severity == "critical")
    warning_count = sum(1 for issue in bundle.quality_issues if issue.severity == "warning")
    unresolved = [record for record in citation_records if not record["resolved"]]
    failed_claims = [item for item in quantitative_claims if item["status"] == "fail"]
    return {
        "status": "critical" if critical_count else "warning" if warning_count or unresolved or failed_claims else "pass",
        "dataset_root": str(bundle.dataset_root),
        "manifest_file_count": len(bundle.evidence.manifest),
        "structured_sources": structured_sources,
        "pdf_sources": pdf_sources,
        "ocr_required": [item for item in pdf_sources if item["needs_ocr"]],
        "ocr_completed": [item for item in pdf_sources if item["ocr_used"] and not item["needs_ocr"]],
        "quality_issues": [asdict(issue) for issue in bundle.quality_issues],
        "citation_summary": {
            "citation_count": len(citation_records),
            "resolved_count": sum(1 for record in citation_records if record["resolved"]),
            "hash_match_count": sum(1 for record in citation_records if record["hash_match"]),
            "unresolved_count": len(unresolved),
        },
        "quantitative_claim_summary": {
            "validated_count": len([item for item in quantitative_claims if item["status"] != "not_applicable"]),
            "pass_count": len([item for item in quantitative_claims if item["status"] == "pass"]),
            "failed_count": len(failed_claims),
        },
        "unresolved_citations": [
            {
                "finding_id": record["finding_id"],
                "source_path": record["source_path"],
                "locator": record["locator"],
                "excerpt": record["excerpt"],
            }
            for record in unresolved
        ],
        "quantitative_claim_failures": failed_claims,
    }


def assess_finding_evidence(bundle: DataBundle, findings: list[Finding]) -> list[dict[str, Any]]:
    resolved_records = resolve_findings(bundle, findings)
    records_by_finding: dict[str, list[dict[str, Any]]] = {}
    for record in resolved_records:
        records_by_finding.setdefault(str(record["finding_id"]), []).append(record)

    assessments: list[dict[str, Any]] = []
    for finding in findings:
        finding_records = records_by_finding.get(finding.finding_id, [])
        resolved_count = sum(1 for record in finding_records if record["resolved"])
        unresolved_records = [
            {
                "source_path": record["source_path"],
                "locator": record["locator"],
            }
            for record in finding_records
            if not record["resolved"]
        ]
        weak_ocr_sources = sorted(
            {
                citation.source_path
                for citation in finding.citations
                if citation.source_path in OCR_REQUIRED_VERIFICATIONS
                and not (_pdf_verification_summary(bundle, citation.source_path) or {}).get("verified")
            }
        )
        reasons: list[str] = []
        if resolved_count < MINIMUM_RESOLVED_CITATIONS_PER_FINDING:
            reasons.append(
                "citation verification insufficient "
                f"({resolved_count}/{MINIMUM_RESOLVED_CITATIONS_PER_FINDING} resolved citations)"
            )
        if resolved_count < MINIMUM_RESOLVED_CITATIONS_PER_FINDING and unresolved_records:
            reasons.append(f"unresolved citations={unresolved_records}")
        if weak_ocr_sources:
            reasons.append(f"OCR verification insufficient for {weak_ocr_sources}")
        rationale_lower = finding.rationale.lower()
        if "ocr-required" in rationale_lower and "missing" in rationale_lower:
            reasons.append("OCR verification insufficient for finding-required evidence")
        assessments.append(
            {
                "finding_id": finding.finding_id,
                "publishable": not reasons,
                "resolved_citations": resolved_count,
                "reasons": reasons,
            }
        )
    return assessments


def apply_fail_closed_evidence_policy(bundle: DataBundle, findings: list[Finding]) -> list[dict[str, Any]]:
    assessments = assess_finding_evidence(bundle, findings)
    findings_by_id = {finding.finding_id: finding for finding in findings}
    for assessment in assessments:
        if assessment["publishable"]:
            continue
        finding = findings_by_id[assessment["finding_id"]]
        finding.confidence = "LOW"
        finding.status = "blocked"
        note = "Fail-closed evidence gate: " + "; ".join(assessment["reasons"])
        if note not in finding.rationale:
            finding.rationale = f"{finding.rationale} {note}".strip()
        remediation_note = "Re-run OCR/citation verification and reopen only after evidence resolves cleanly."
        if remediation_note not in finding.remediation:
            finding.remediation = f"{finding.remediation} {remediation_note}".strip()
    return assessments


def save_data_quality_report(report: dict[str, Any], run_dir: Path) -> dict[str, Path]:
    run_dir.mkdir(parents=True, exist_ok=True)
    json_path = run_dir / "StrategyOS Data Quality Report.json"
    md_path = run_dir / "StrategyOS Data Quality Report.md"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_data_quality_report(report), encoding="utf-8")
    return {"data_quality_json": json_path, "data_quality_md": md_path}


def render_data_quality_report(report: dict[str, Any]) -> str:
    lines = [
        "# StrategyOS Data Quality Report",
        "",
        f"- Status: {report['status']}",
        f"- Dataset root: {report['dataset_root']}",
        f"- Manifest file count: {report['manifest_file_count']}",
        f"- Citation resolved: {report['citation_summary']['resolved_count']} of {report['citation_summary']['citation_count']}",
        f"- Citation hash matches: {report['citation_summary']['hash_match_count']} of {report['citation_summary']['citation_count']}",
        f"- Quantitative claims validated: {report['quantitative_claim_summary']['pass_count']} of {report['quantitative_claim_summary']['validated_count']}",
        f"- OCR completed sources: {len(report['ocr_completed'])}",
        f"- OCR still required sources: {len(report['ocr_required'])}",
        "",
        "## Structured Sources",
        "",
    ]
    for source in report["structured_sources"]:
        lines.append(f"- {source['name']}: {source['rows']} rows, {source['columns']} columns")
    lines.extend(["", "## OCR / PDF Extraction", ""])
    for source in report["pdf_sources"]:
        if source["needs_ocr"]:
            marker = "OCR STILL REQUIRED"
        elif source["ocr_used"]:
            marker = f"OCR completed ({source['ocr_engine']})"
        else:
            marker = "text extracted"
        verification = ""
        if source["verification"]:
            verification = "; verification=" + ("verified" if source["verification"]["verified"] else "missing")
        lines.append(f"- {source['source_path']}: {marker}; pages={source['pages']}; empty_pages={source['empty_pages']}; chars={source['text_chars']}{verification}")
    if report["quality_issues"]:
        lines.extend(["", "## Quality Issues", ""])
        for issue in report["quality_issues"]:
            lines.append(f"- {issue['severity'].upper()} - {issue['source']}: {issue['detail']}")
    if report["unresolved_citations"]:
        lines.extend(["", "## Unresolved Citations", ""])
        for citation in report["unresolved_citations"]:
            lines.append(f"- {citation['finding_id']}: {citation['source_path']} - {citation['locator']}")
    if report["quantitative_claim_failures"]:
        lines.extend(["", "## Quantitative Claim Failures", ""])
        for item in report["quantitative_claim_failures"]:
            failed_checks = ", ".join(check["name"] for check in item["checks"] if not check["passed"])
            lines.append(f"- {item['finding_id']} ({item['pattern_type']}): {failed_checks}")
    return "\n".join(lines)


def structured_source_summary(bundle: DataBundle) -> list[dict[str, Any]]:
    sources = [
        ("AP", bundle.ap),
        ("AR", bundle.ar),
        ("GL", bundle.gl),
        ("Trial Balance", bundle.trial_balance),
        ("Vendor Master", bundle.vendors),
        ("Customer Master", bundle.customers),
        ("Chart of Accounts", bundle.coa),
        ("PO Log", bundle.po),
    ]
    return [
        {
            "name": name,
            "rows": int(len(df)),
            "columns": int(len(df.columns)),
            "column_names": list(df.columns),
            "null_counts": {str(k): int(v) for k, v in df.isna().sum().to_dict().items()},
        }
        for name, df in sources
    ]


def pdf_source_summary(bundle: DataBundle) -> list[dict[str, Any]]:
    summary = []
    for rel_path, pages in sorted(bundle.evidence.pdf_text.items()):
        ocr_status = bundle.evidence.ocr_status.get(rel_path, {})
        unresolved_ocr = [
            page for page in ocr_status.get("pages", [])
            if page.get("status") != "ok"
        ]
        text_chars = sum(len(page.strip()) for page in pages)
        empty_pages = sum(1 for page in pages if not page.strip())
        summary.append(
            {
                "source_path": rel_path,
                "pages": len(pages),
                "empty_pages": empty_pages,
                "text_chars": text_chars,
                "ocr_used": bool(ocr_status.get("required")),
                "ocr_engine": ocr_status.get("engine"),
                "ocr_status": ocr_status,
                "needs_ocr": bool(ocr_status.get("blocked_reason") or unresolved_ocr or empty_pages or text_chars == 0),
                "verification": _pdf_verification_summary(bundle, rel_path),
            }
        )
    return summary


def _pdf_verification_summary(bundle: DataBundle, rel_path: str) -> dict[str, Any] | None:
    label, terms = OCR_REQUIRED_VERIFICATIONS.get(rel_path, (None, ()))
    if not label:
        return None
    excerpt = bundle.evidence.pdf_excerpt(rel_path, terms)
    return {
        "label": label,
        "required_terms": list(terms),
        "verified": bool(excerpt),
        "excerpt": excerpt,
        "ocr_required": bool(bundle.evidence.ocr_status.get(rel_path, {}).get("required")),
    }
