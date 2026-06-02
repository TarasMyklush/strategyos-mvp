from __future__ import annotations

import json
from pathlib import Path

from ..ingestion import DataBundle
from ..knowledge_graph import build_knowledge_graph, save_knowledge_graph
from ..models import AuditEvent, Finding
from ..skills.finance_controls import compute_working_capital_drifts, run_all_finance_skills


class FinanceAnalystAgent:
    name = "Finance Analyst"

    def draft_findings(self, bundle: DataBundle) -> list[Finding]:
        return run_all_finance_skills(bundle)


class FinanceAuditorAgent:
    name = "Finance Auditor"

    def challenge_findings(self, findings: list[Finding]) -> list[AuditEvent]:
        events: list[AuditEvent] = []
        for finding in findings:
            issues = []
            if len(finding.citations) < 3:
                issues.append("Finding has fewer than three citations.")
            if finding.recoverable_sar > finding.leakage_sar + 0.01:
                issues.append("Recoverable amount exceeds leakage amount.")
            if finding.recoverable_sar and not finding.calculation:
                issues.append("Recoverable finding lacks calculation trace.")
            if issues:
                finding.status = "challenged"
                finding.challenges.extend(issues)
                finding.confidence = "MEDIUM" if finding.confidence == "HIGH" else finding.confidence
                for issue in issues:
                    events.append(AuditEvent(1, self.name, finding.finding_id, "challenge", issue))
            else:
                finding.status = "locked"
                events.append(AuditEvent(1, self.name, finding.finding_id, "lock", "Finding has minimum citation and calculation support."))
        return events


class KnowledgeGraphAgent:
    name = "Knowledge Graph Builder"

    def build(self, bundle: DataBundle, findings: list[Finding], run_dir: Path) -> Path:
        graph = build_knowledge_graph(bundle, findings)
        return save_knowledge_graph(graph, run_dir / "StrategyOS Knowledge Graph.json")


class CaseFileWriter:
    name = "Case File Writer"

    def write_all(self, bundle: DataBundle, findings: list[Finding], audit_events: list[AuditEvent], run_dir: Path) -> dict[str, Path]:
        run_dir.mkdir(parents=True, exist_ok=True)
        case_file = run_dir / "StrategyOS Cash Leakage Case File.md"
        wc_memo = run_dir / "StrategyOS Working Capital Drift Memo.md"
        qa = run_dir / "StrategyOS Drilldown QA Transcript.md"
        audit = run_dir / "StrategyOS Ping Pong Audit Log.json"

        case_file.write_text(render_case_file(findings, bundle), encoding="utf-8")
        wc_memo.write_text(render_working_capital(bundle), encoding="utf-8")
        qa.write_text(render_qa(findings), encoding="utf-8")
        audit.write_text(json.dumps([event.__dict__ for event in audit_events], indent=2), encoding="utf-8")
        return {"case_file": case_file, "working_capital": wc_memo, "qa": qa, "audit_log": audit}


def render_case_file(findings: list[Finding], bundle: DataBundle) -> str:
    total_leakage = sum(f.leakage_sar for f in findings)
    total_recoverable = sum(f.recoverable_sar for f in findings)
    lines = [
        "# StrategyOS Cash Leakage Case File",
        "",
        "## Executive Summary",
        "",
        f"- Total leakage identified: SAR {total_leakage:,.2f}",
        f"- Total recoverable identified: SAR {total_recoverable:,.2f}",
        f"- Locked findings: {sum(f.status == 'locked' for f in findings)} of {len(findings)}",
        "- Methodology: deterministic source ingestion, evidence hashing, finance-control skills, Analyst draft, Auditor challenge, and cited case-file generation.",
        "",
    ]
    for finding in findings:
        lines.extend(
            [
                f"## {finding.finding_id} - {finding.title}",
                "",
                f"- Pattern type: {finding.pattern_type}",
                f"- Vendor/entity: {finding.vendor_name} ({finding.vendor_id})",
                f"- Classification: {finding.classification}",
                f"- Leakage: SAR {finding.leakage_sar:,.2f}",
                f"- Recoverable: SAR {finding.recoverable_sar:,.2f} / USD {finding.recoverable_usd:,.2f}",
                f"- Confidence: {finding.confidence}",
                f"- Status: {finding.status}",
                f"- Rationale: {finding.rationale}",
                f"- Remediation: {finding.remediation}",
                "",
                "### Evidence",
            ]
        )
        for citation in finding.citations:
            excerpt = f" - {citation.excerpt}" if citation.excerpt else ""
            lines.append(f"- {citation.label()}{excerpt}")
        if finding.challenges:
            lines.append("")
            lines.append("### Auditor Challenges")
            lines.extend(f"- {challenge}" for challenge in finding.challenges)
        lines.append("")
    if bundle.quality_issues:
        lines.extend(["## Data Quality Notes", ""])
        for issue in bundle.quality_issues:
            lines.append(f"- {issue.severity.upper()} - {issue.source}: {issue.detail}")
    return "\n".join(lines)


def render_working_capital(bundle: DataBundle) -> str:
    signals = compute_working_capital_drifts(bundle)
    lines = ["# StrategyOS Working Capital Drift Memo", "", "Formula: days metric = collection/payment date minus invoice date; baseline = average first three H1 months.", ""]
    for i, signal in enumerate(signals, start=1):
        lines.extend(
            [
                f"## Signal {i}: {signal['metric']} drift in {signal['period']}",
                "",
                f"- Baseline days: {signal['baseline_days']}",
                f"- Current days: {signal['current_days']}",
                f"- Drift days: {signal['drift_days']}",
                f"- Estimated cash impact: SAR {signal['cash_impact_sar']:,.2f}",
                f"- Driver records: {', '.join(signal['drivers'])}",
                "",
            ]
        )
    return "\n".join(lines)


def render_qa(findings: list[Finding]) -> str:
    recoverable = sorted(findings, key=lambda f: f.recoverable_sar, reverse=True)
    top = recoverable[0] if recoverable else None
    top_five = recoverable[:5]
    recurring = [f for f in recoverable if "going-forward" in f.classification.lower()]
    lines = ["# StrategyOS Drilldown Q&A Transcript", ""]
    if top:
        lines.extend([
            "## Q1. Which vendor has the largest single-event cash leakage?",
            "",
            f"{top.vendor_name} ({top.vendor_id}) has the largest recoverable finding in this run: SAR {top.recoverable_sar:,.2f}. Evidence is listed in {top.finding_id}.",
            "",
        ])
    lines.extend([
        "## Q2. What is the top-five recovery impact?",
        "",
        f"Top-five recoverable amount: SAR {sum(f.recoverable_sar for f in top_five):,.2f}. EBITDA margin impact requires final GL/TB classification sign-off before publication.",
        "",
        "## Q3. Which patterns would recur in H2?",
        "",
    ])
    if recurring:
        for finding in recurring:
            lines.append(f"- {finding.title}: SAR {finding.recoverable_sar:,.2f} H1 exposure, recurring unless process/contract control is fixed.")
    else:
        lines.append("- No recurring exposure classified by current deterministic run.")
    return "\n".join(lines)
