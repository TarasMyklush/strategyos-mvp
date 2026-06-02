from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .citation_resolver import resolve_findings
from .ingestion import DataBundle
from .models import Finding


def build_data_quality_report(bundle: DataBundle, findings: list[Finding]) -> dict[str, Any]:
    structured_sources = structured_source_summary(bundle)
    pdf_sources = pdf_source_summary(bundle)
    citation_records = resolve_findings(bundle, findings)
    critical_count = sum(1 for issue in bundle.quality_issues if issue.severity == "critical")
    warning_count = sum(1 for issue in bundle.quality_issues if issue.severity == "warning")
    unresolved = [record for record in citation_records if not record["resolved"]]
    return {
        "status": "critical" if critical_count else "warning" if warning_count or unresolved else "pass",
        "dataset_root": str(bundle.dataset_root),
        "manifest_file_count": len(bundle.evidence.manifest),
        "structured_sources": structured_sources,
        "pdf_sources": pdf_sources,
        "ocr_required": [item for item in pdf_sources if item["needs_ocr"]],
        "quality_issues": [asdict(issue) for issue in bundle.quality_issues],
        "citation_summary": {
            "citation_count": len(citation_records),
            "resolved_count": sum(1 for record in citation_records if record["resolved"]),
            "hash_match_count": sum(1 for record in citation_records if record["hash_match"]),
            "unresolved_count": len(unresolved),
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
    }


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
        f"- OCR required sources: {len(report['ocr_required'])}",
        "",
        "## Structured Sources",
        "",
    ]
    for source in report["structured_sources"]:
        lines.append(f"- {source['name']}: {source['rows']} rows, {source['columns']} columns")
    lines.extend(["", "## OCR / PDF Extraction", ""])
    for source in report["pdf_sources"]:
        marker = "OCR REQUIRED" if source["needs_ocr"] else "text extracted"
        lines.append(f"- {source['source_path']}: {marker}; pages={source['pages']}; empty_pages={source['empty_pages']}; chars={source['text_chars']}")
    if report["quality_issues"]:
        lines.extend(["", "## Quality Issues", ""])
        for issue in report["quality_issues"]:
            lines.append(f"- {issue['severity'].upper()} - {issue['source']}: {issue['detail']}")
    if report["unresolved_citations"]:
        lines.extend(["", "## Unresolved Citations", ""])
        for citation in report["unresolved_citations"]:
            lines.append(f"- {citation['finding_id']}: {citation['source_path']} - {citation['locator']}")
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
        text_chars = sum(len(page.strip()) for page in pages)
        empty_pages = sum(1 for page in pages if not page.strip())
        summary.append(
            {
                "source_path": rel_path,
                "pages": len(pages),
                "empty_pages": empty_pages,
                "text_chars": text_chars,
                "needs_ocr": bool(empty_pages or text_chars == 0),
            }
        )
    return summary
