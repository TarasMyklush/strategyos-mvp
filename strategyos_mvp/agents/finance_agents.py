from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from datetime import UTC, datetime
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, PageBreak

from ..citation_resolver import save_citation_audit
from ..ingestion import DataBundle
from ..knowledge_graph import build_knowledge_graph, save_knowledge_graph
from ..models import AuditEvent, Finding
from ..quality import (
    apply_fail_closed_evidence_policy,
    assess_finding_evidence,
    build_data_quality_report,
    save_data_quality_report,
)
from ..runtime_artifacts import AUDIT_LOG_FILENAME
from ..prompt_injection import document_excerpt_for_display
from ..skills.finance_controls import compute_working_capital_drifts, run_all_finance_skills, _role_source_path


class FinanceAnalystAgent:
    name = "Finance Analyst"

    def draft_findings(self, bundle: DataBundle) -> list[Finding]:
        return run_all_finance_skills(bundle)

    def respond_to_challenges(
        self,
        findings: list[Finding],
        challenged_findings: dict[str, str],
        *,
        round_no: int,
    ) -> list[AuditEvent]:
        findings_by_id = {finding.finding_id: finding for finding in findings}
        events: list[AuditEvent] = []
        for finding_id, challenge in challenged_findings.items():
            finding = findings_by_id[finding_id]
            before = finding.confidence
            was_blocked = finding.status == "blocked"
            response = self._build_response(finding, challenge)
            finding.confidence = self._updated_confidence(finding, challenge)
            finding.status = "blocked" if was_blocked else "draft"
            events.append(
                _audit_event(
                    round_no=round_no,
                    actor=self.name,
                    finding_id=finding.finding_id,
                    action="response",
                    detail=response,
                    challenge=challenge,
                    response=response,
                    status="responded",
                    confidence_before=before,
                    confidence_after=finding.confidence,
                )
            )
        return events

    def _build_response(self, finding: Finding, challenge: str) -> str:
        lower = challenge.lower()
        parts: list[str] = []
        if "fewer than three citations" in lower:
            parts.append(
                f"Current packet carries {len(finding.citations)} citation(s); Phase 3 keeps scope to analyst/auditor review without adding new evidence-chain work."
            )
        if "recoverable amount exceeds leakage amount" in lower:
            parts.append(
                f"Recoverable SAR {finding.recoverable_sar:,.2f} is being treated conservatively against leakage SAR {finding.leakage_sar:,.2f}."
            )
        if "calculation trace" in lower:
            parts.append(
                "Calculation trace is "
                + ("present in the finding payload." if finding.calculation else "not yet attached to the finding payload.")
            )
        if "evidence verification required" in lower:
            parts.append(
                f"Analyst confirms {len(finding.citations)} citation(s), confidence {finding.confidence}, and recoverable SAR {finding.recoverable_sar:,.2f} for auditor review; this response alone does not resolve an evidence defect."
            )
        if not parts:
            parts.append(
                f"Analyst reviewed {finding.finding_id} and stands behind the deterministic draft with confidence {finding.confidence}."
            )
        return " ".join(parts)

    def _updated_confidence(self, finding: Finding, challenge: str) -> str:
        lower = challenge.lower()
        if any(
            marker in lower
            for marker in (
                "fewer than three citations",
                "recoverable amount exceeds leakage amount",
                "calculation trace",
            )
        ):
            return _downgrade_confidence(finding.confidence)
        return finding.confidence


class FinanceAuditorAgent:
    name = "Finance Auditor"
    max_rounds = 10
    minimum_challenged_findings = 4

    def required_challenges(self, findings: list[Finding]) -> int:
        return len({finding.finding_id for finding in findings})

    def challenge_findings(self, findings: list[Finding]) -> list[AuditEvent]:
        return self.run_review_rounds(findings)

    def run_review_rounds(
        self,
        findings: list[Finding],
        *,
        analyst: FinanceAnalystAgent | None = None,
        max_rounds: int | None = None,
    ) -> list[AuditEvent]:
        analyst = analyst or FinanceAnalystAgent()
        audit_events: list[AuditEvent] = []
        max_rounds = self.max_rounds if max_rounds is None else max_rounds
        if isinstance(max_rounds, bool) or not isinstance(max_rounds, int) or not 1 <= max_rounds <= self.max_rounds:
            raise ValueError("Auditor review requires between one and ten rounds.")
        if len({finding.finding_id for finding in findings}) != len(findings):
            raise ValueError("Auditor review requires unique finding identities.")
        challenged_once: set[str] = set()
        responded_once: set[str] = set()
        round_no = 1

        while round_no <= max_rounds:
            challenges = self._select_round_challenges(findings, challenged_once)
            if not challenges:
                self._lock_ready_findings(findings, audit_events, responded_once, round_no)
                break

            for finding in findings:
                challenge = challenges.get(finding.finding_id)
                if challenge is None:
                    continue
                if finding.status != "blocked":
                    finding.status = "challenged"
                finding.challenges.append(challenge)
                challenged_once.add(finding.finding_id)
                audit_events.append(
                    _audit_event(
                        round_no=round_no,
                        actor=self.name,
                        finding_id=finding.finding_id,
                        action="challenge",
                        detail=challenge,
                        challenge=challenge,
                        status="challenged",
                        confidence_before=finding.confidence,
                        confidence_after=finding.confidence,
                    )
                )

            analyst_events = analyst.respond_to_challenges(
                findings,
                challenges,
                round_no=round_no,
            )
            responded_once.update(event.finding_id for event in analyst_events)
            audit_events.extend(analyst_events)
            self._lock_ready_findings(findings, audit_events, responded_once, round_no)
            round_no += 1

        if any(finding.status != "locked" for finding in findings):
            for finding in findings:
                if finding.status == "locked":
                    continue
                if finding.status != "blocked":
                    finding.status = "disputed"
                audit_events.append(
                    _audit_event(
                        round_no=max_rounds,
                        actor=self.name,
                        finding_id=finding.finding_id,
                        action="max_rounds",
                        detail="Audit loop hit max rounds before lock.",
                        status=finding.status,
                        confidence_before=finding.confidence,
                        confidence_after=finding.confidence,
                    )
                )

        self.last_verification = self.verify_acceptance_coverage(findings, audit_events)
        if not self.last_verification["passed"]:
            raise RuntimeError(self.last_verification["detail"])
        return audit_events

    def verify_acceptance_coverage(
        self, findings: list[Finding], audit_events: list[AuditEvent]
    ) -> dict[str, object]:
        finding_ids = {finding.finding_id for finding in findings}
        challenged_finding_ids = {
            event.finding_id
            for event in audit_events
            if event.actor == self.name and event.action == "challenge" and event.finding_id in finding_ids
        }
        required = self.required_challenges(findings)
        passed = len(challenged_finding_ids) >= required
        return {
            "passed": passed,
            "required_challenged_findings": required,
            "actual_challenged_findings": len(challenged_finding_ids),
            "challenged_finding_ids": sorted(challenged_finding_ids),
            "rounds_completed": max((event.round_no for event in audit_events), default=0),
            "detail": (
                f"Acceptance-sensitive verification required {required} challenged findings; "
                f"observed {len(challenged_finding_ids)}."
            ),
        }

    def _select_round_challenges(
        self, findings: list[Finding], challenged_once: set[str]
    ) -> dict[str, str]:
        challenge_map: dict[str, str] = {}
        required = self.required_challenges(findings)
        for finding in self._sorted_review_candidates(findings):
            if finding.status == "locked":
                continue
            issues = self._issues_for_finding(finding)
            if issues:
                challenge_map[finding.finding_id] = " ".join(issues)

        if len(challenged_once) + len(challenge_map) >= required:
            return challenge_map

        for finding in self._sorted_review_candidates(findings):
            if finding.status == "locked":
                continue
            if finding.finding_id in challenged_once or finding.finding_id in challenge_map:
                continue
            challenge_map[finding.finding_id] = (
                "Evidence verification required for every finding before lock. "
                f"Confirm citation sufficiency ({len(finding.citations)} citation(s)) and recoverable logic."
            )
            if len(challenged_once) + len(challenge_map) >= required:
                break
        return challenge_map

    def _sorted_review_candidates(self, findings: list[Finding]) -> list[Finding]:
        return sorted(
            findings,
            key=lambda item: (
                0 if self._is_weak_finding(item) else 1,
                -item.recoverable_sar,
                item.finding_id,
            ),
        )

    def _is_weak_finding(self, finding: Finding) -> bool:
        return finding.confidence != "HIGH" or bool(self._issues_for_finding(finding))

    def _issues_for_finding(self, finding: Finding) -> list[str]:
        issues: list[str] = []
        distinct_citations = {(citation.source_path, citation.locator) for citation in finding.citations}
        if len(distinct_citations) < 3:
            issues.append("Finding has fewer than three citations to distinct source locations.")
        if finding.status == "blocked":
            issues.append("Finding is blocked by fail-closed evidence verification.")
        if finding.recoverable_sar > finding.leakage_sar + 0.01:
            issues.append("Recoverable amount exceeds leakage amount.")
        if finding.recoverable_sar and not finding.calculation:
            issues.append("Recoverable finding lacks calculation trace.")
        return issues

    def _lock_ready_findings(
        self,
        findings: list[Finding],
        audit_events: list[AuditEvent],
        responded_once: set[str],
        round_no: int,
    ) -> None:
        for finding in findings:
            if finding.status == "locked":
                continue
            if finding.status == "blocked":
                audit_events.append(
                    _audit_event(
                        round_no=round_no,
                        actor=self.name,
                        finding_id=finding.finding_id,
                        action="block",
                        detail="Finding remains blocked by fail-closed evidence verification.",
                        status="blocked",
                        confidence_before=finding.confidence,
                        confidence_after=finding.confidence,
                    )
                )
                continue
            if finding.finding_id not in responded_once or self._issues_for_finding(finding):
                continue
            detail = (
                "Finding locked after analyst response and evidence checks."
                if finding.finding_id in responded_once
                else "Finding locked without additional challenge."
            )
            finding.status = "locked"
            audit_events.append(
                _audit_event(
                    round_no=round_no,
                    actor=self.name,
                    finding_id=finding.finding_id,
                    action="lock",
                    detail=detail,
                    status="locked",
                    confidence_before=finding.confidence,
                    confidence_after=finding.confidence,
                )
            )


def _downgrade_confidence(confidence: str) -> str:
    if confidence == "HIGH":
        return "MEDIUM"
    if confidence == "MEDIUM":
        return "LOW"
    return confidence


def _confidence_change(before: str | None, after: str | None) -> str:
    if before == after:
        return "UNCHANGED"
    return f"{before or 'UNKNOWN'}->{after or 'UNKNOWN'}"


def _audit_event(
    *,
    round_no: int,
    actor: str,
    finding_id: str,
    action: str,
    detail: str,
    challenge: str | None = None,
    response: str | None = None,
    status: str,
    confidence_before: str | None,
    confidence_after: str | None,
) -> AuditEvent:
    timestamp = datetime.now(UTC).isoformat()
    return AuditEvent(
        round_no=round_no,
        actor=actor,
        finding_id=finding_id,
        action=action,
        detail=detail,
        challenge=challenge,
        response=response,
        status=status,
        confidence_before=confidence_before,
        confidence_after=confidence_after,
        confidence_change=_confidence_change(confidence_before, confidence_after),
        started_at=timestamp,
        completed_at=timestamp,
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        estimated_cost_usd=None,
    )


class KnowledgeGraphAgent:
    name = "Knowledge Graph Builder"

    def build(self, bundle: DataBundle, findings: list[Finding], run_dir: Path) -> Path:
        graph = build_knowledge_graph(bundle, findings)
        return save_knowledge_graph(graph, run_dir / "StrategyOS Knowledge Graph.json")


class EvidenceQAAgent:
    name = "Evidence QA"

    def write_reports(self, bundle: DataBundle, findings: list[Finding], run_dir: Path) -> dict[str, Path]:
        report = build_data_quality_report(bundle, findings)
        artifacts = save_data_quality_report(report, run_dir)
        artifacts["citation_audit"] = save_citation_audit(bundle, findings, run_dir / "StrategyOS Citation Audit.json")
        return artifacts


class CaseFileWriter:
    name = "Case File Writer"

    def write_all(self, bundle: DataBundle, findings: list[Finding], audit_events: list[AuditEvent], run_dir: Path) -> dict[str, Path]:
        run_dir.mkdir(parents=True, exist_ok=True)
        apply_fail_closed_evidence_policy(bundle, findings)
        blocked = [
            assessment
            for assessment in assess_finding_evidence(bundle, findings)
            if not assessment["publishable"]
        ]
        run_mode = str((getattr(bundle, "run_metadata", {}) or {}).get("run_mode") or "full")
        if blocked:
            detail = "; ".join(
                f"{item['finding_id']}: {', '.join(item['reasons'])}"
                for item in blocked
            )
            if run_mode != "partial":
                # Full run against a complete dataset: a finding that cannot meet
                # the evidence bar is a genuine regression — fail closed.
                raise ValueError(
                    "Cannot produce polished outputs from weak evidence. " + detail
                )
            # Partial run: corroborating roles may be legitimately absent. Withhold
            # the weak findings from the published case file (they are already
            # marked blocked/LOW by the fail-closed policy) rather than crashing.
            blocked_ids = {item["finding_id"] for item in blocked}
            withheld = [f for f in findings if f.finding_id in blocked_ids]
            findings = [f for f in findings if f.finding_id not in blocked_ids]
            bundle.run_metadata["withheld_findings"] = [
                {
                    "finding_id": item["finding_id"],
                    "reasons": item["reasons"],
                }
                for item in blocked
            ]
        case_file_md = run_dir / "Final consolidated case file.md"
        case_file_pdf = run_dir / "Final consolidated case file.pdf"
        wc_memo = run_dir / "Working capital drift memo.md"
        qa = run_dir / "Drill-down Q&A transcript.md"
        audit = run_dir / AUDIT_LOG_FILENAME

        case_file_markdown = render_case_file(findings, bundle)
        case_file_md.write_text(case_file_markdown, encoding="utf-8")
        write_markdown_pdf(
            case_file_markdown,
            case_file_pdf,
            title="Final consolidated case file",
        )
        wc_memo.write_text(render_working_capital(bundle, findings), encoding="utf-8")
        qa.write_text(render_qa(findings, bundle), encoding="utf-8")
        audit.write_text(json.dumps([event.__dict__ for event in audit_events], indent=2), encoding="utf-8")
        return {
            "case_file": case_file_md,
            "case_file_pdf": case_file_pdf,
            "working_capital": wc_memo,
            "qa": qa,
            "audit_log": audit,
        }


def render_case_file(findings: list[Finding], bundle: DataBundle) -> str:
    findings = sorted(findings, key=lambda finding: (-finding.recoverable_sar, finding.finding_id))
    total_leakage = sum(f.leakage_sar for f in findings)
    total_recoverable = sum(f.recoverable_sar for f in findings)
    lines = [
        "# Final consolidated case file",
        "",
        "## Executive Summary",
        "",
        f"- Total leakage identified: SAR {total_leakage:,.2f}",
        f"- Total recoverable identified: SAR {total_recoverable:,.2f}",
        f"- Locked findings: {sum(f.status == 'locked' for f in findings)} of {len(findings)}",
        f"- Detector coverage: {_detector_summary(bundle)}",
        "- Methodology: deterministic source ingestion, evidence hashing, finance-control skills, Analyst draft, Auditor challenge, and cited case-file generation.",
        "",
    ]
    lines.extend(['### Top three recovery opportunities', ''])
    for finding in findings[:3]:
        lines.append(f'- {finding.title}: SAR {finding.recoverable_sar:,.2f} recoverable ({finding.confidence.lower()} confidence).')
    lines.extend(['', '<!-- pagebreak -->', '', '## Findings', ''])
    for finding in findings:
        lines.extend(
            [
                f"## {finding.finding_id} - {finding.title}",
                "",
                f"- Pattern type: {finding.pattern_type.replace('_', ' ')}",
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
            lines.append(f"- {citation.label()}")
            if citation.excerpt:
                lines.extend('> ' + line for line in document_excerpt_for_display(citation.excerpt).splitlines())
        if finding.challenges:
            lines.append("")
            lines.append("### Auditor Challenges")
            lines.extend(f"- {challenge}" for challenge in finding.challenges)
        lines.append("")
    disputed = [finding for finding in findings if finding.status == 'disputed']
    lines.extend(['## Disputed findings', ''])
    if not disputed:
        lines.append('No findings are recorded as disputed in this reviewed case file.')
    for finding in disputed:
        lines.append(f'- {finding.finding_id}: {finding.title}. Unresolved auditor challenges remain listed with the finding for human resolution.')
    sources = sorted({citation.source_path for finding in findings for citation in finding.citations})
    lines.extend(['', '## Methodology and source coverage', '',
        f'- Findings cite {len(sources)} distinct source documents and {len({finding.vendor_id for finding in findings})} vendor identifiers.',
        '- Vendor identities and recovery calculations are retained with each finding and its row-level evidence. Identified leakage and recoverable value are separate measures; control-dependent and going-forward amounts are not booked cash receipts.',
        '- The source manifest records inspected file identities. Registering a file does not establish that every possible pattern in it was tested.', ''])
    lines.extend(_render_detector_coverage(bundle))
    if bundle.quality_issues:
        lines.extend(["## Data Quality Notes", ""])
        for issue in bundle.quality_issues:
            lines.append(f"- {issue.severity.upper()} - {issue.source}: {issue.detail}")
    return "\n".join(lines)


def render_working_capital(bundle: DataBundle, findings: list[Finding]) -> str:
    signals = compute_working_capital_drifts(bundle, findings)
    lines = [
        "# 13-week settlement-day proxy drift analysis",
        "",
        "These collection/payment timing proxies exclude unpaid balances. They are not balance-based DSO/DPO, and the estimated cash effects are not verified receipts.",
        "",
        "## Method",
        "",
        "- Formula 1: invoice days = settlement date minus invoice date (collection date for DSO, payment date for DPO).",
        "- Formula 2: weekly days = average invoice days for invoices raised in each invoice week.",
        "- Formula 3: 13-week baseline = average weekly days across the latest 13 completed invoice weeks for that metric.",
        "- Formula 4: drift days = current week days minus 13-week baseline days.",
        "- Formula 5: cash impact (SAR) = weekly SAR amount x |drift days| / current week days.",
        "- Cash direction rule: DSO drift up = cash absorbed, DSO drift down = cash released; DPO drift up = cash released, DPO drift down = cash absorbed.",
        "- Selection rule: rank qualifying weeks by absolute cash impact and force DSO/DPO coverage when both metrics have qualifying weeks.",
        "",
        "## Top 3 drift signals",
        "",
    ]
    for i, signal in enumerate(signals, start=1):
        overlap = signal["task1_overlap"]
        overlap_note = "none detected"
        if overlap["invoice_ids"]:
            overlap_note = (
                f"already tied to Task 1 via {', '.join(overlap['invoice_ids'])} "
                f"({', '.join(overlap['finding_ids'])}); do not add this signal on top of Task 1 leakage"
            )
        lines.extend(
            [
                f"## Signal {i}: {signal.get('display_label', signal['metric'])} week ending {signal['week_end']}",
                "",
                f"- 13-week baseline days: {signal['baseline_days']}",
                f"- Current week days: {signal['current_days']}",
                f"- Drift days: {signal['drift_days']}",
                f"- Weekly amount: SAR {signal['weekly_amount_sar']:,.2f}",
                f"- Cash impact: SAR {signal['cash_impact_sar']:,.2f} {signal['cash_effect']}",
                f"- Classification: {signal['classification'].upper()} - {signal['classification_reason']}",
                f"- Task 1 leakage overlap: {overlap_note}",
                "- Driver citations:",
                "",
            ]
        )
        for driver in signal["drivers"]:
            citation = driver["citation"]
            note = ""
            if driver["task1_overlap_findings"]:
                note = f"; Task 1 overlap {', '.join(driver['task1_overlap_findings'])}"
            lines.append(
                "  - "
                f"{driver['invoice_id']} / {driver['counterparty']} / SAR {driver['amount_sar']:,.2f} / {driver['days']} days "
                f"[{citation.label()}]{note}"
            )
        lines.append("")
    return "\n".join(lines)


def render_qa(findings: list[Finding], bundle: DataBundle) -> str:
    recoverable = sorted(findings, key=lambda f: f.recoverable_sar, reverse=True)
    top_five = recoverable[:5]
    top_single_event = max(recoverable, key=_single_event_leakage_sar, default=None)
    recurring = [f for f in recoverable if "going-forward" in f.classification.lower()]
    non_recurring = [
        f for f in recoverable if f.recoverable_sar > 0 and "going-forward" not in f.classification.lower()
    ]
    ebitda = _compute_ebitda_baseline(bundle)
    ebitda_recovery = sum(f.recoverable_sar for f in top_five if _finding_affects_ebitda(f))
    non_ebitda_recovery = sum(f.recoverable_sar for f in top_five) - ebitda_recovery
    recurring_h2 = sum(f.recoverable_sar for f in recurring)
    recurring_h2_ebitda = sum(f.recoverable_sar for f in recurring if _finding_affects_ebitda(f))
    lines = ["# Drill-down Q&A transcript", ""]
    lines.extend([
        "## Detector coverage",
        "",
        _detector_summary(bundle),
        "",
    ])
    for item in _skipped_detector_lines(bundle):
        lines.append(f"- {item}")
    if _skipped_detector_lines(bundle):
        lines.append("")
    if top_single_event:
        single_event = _single_event_leakage_sar(top_single_event)
        lines.extend([
            "## Q1. Which vendor has the largest single-event cash leakage?",
            "",
            f"{top_single_event.vendor_name} ({top_single_event.vendor_id}) has the largest single-event cash leakage in this run: SAR {single_event:,.2f}. The event sits in {top_single_event.finding_id} ({top_single_event.title}).",
            f"Direct citations: {_citation_list(top_single_event.citations, limit=4)}.",
            "",
        ])
    else:
        lines.extend(['## Q1. Which vendor has the largest single-event cash leakage?', '',
                      'No evidence-qualified finding is available to identify a largest leakage event.', ''])
    lines.extend([
        "## Q2. What is the top-five recovery impact?",
        "",
        f"Top-five gross recoverable opportunity: SAR {sum(f.recoverable_sar for f in top_five):,.2f} across {', '.join(f.finding_id for f in top_five)}.",
    ])
    if ebitda.get("available"):
        lines.extend([
            'Scope: the supplied GL and trial balance; group consolidation is not inferred.',
            f"Baseline H1 EBITDA from GL/TB: SAR {ebitda['baseline_ebitda_sar']:,.2f} on revenue SAR {ebitda['revenue_sar']:,.2f}, for an EBITDA margin of {ebitda['baseline_margin']:.2%} before recovery.",
            f"Of the top five, SAR {ebitda_recovery:,.2f} maps directly to current-period EBITDA lines; pro-forma EBITDA becomes SAR {ebitda['baseline_ebitda_sar'] + ebitda_recovery:,.2f} and margin becomes {((ebitda['baseline_ebitda_sar'] + ebitda_recovery) / ebitda['revenue_sar']):.2%}.",
            f"The remaining SAR {non_ebitda_recovery:,.2f} is recovery value, but not H1 EBITDA uplift: prior-period credit / balance-sheet recovery plus control-dependent exposure remain outside the EBITDA bridge until separately realized.",
            f"Baseline citations: {_format_ebitda_citations(ebitda)}.",
        ])
    else:
        lines.append(
            "EBITDA bridge not computed for this run: " + ebitda.get('reason', 'A verified baseline is unavailable.')
        )
    lines.extend([
        "",
        "Top-five finding citations: " + '; '.join(
            f"{finding.finding_id}: SAR {finding.recoverable_sar:,.2f}, {finding.title}, {_impact_label(finding)} [{_citation_list(finding.citations, limit=3)}]"
            for finding in top_five),
    ])
    lines.extend([
        "",
        "## Q3. Which patterns would recur in H2?",
        "",
    ])
    if recurring:
        lines.append(
            f"Projected H2 recurring exposure is SAR {recurring_h2:,.2f} if H2 mirrors H1 and the cited process/contract failures remain unfixed. Of that, SAR {recurring_h2_ebitda:,.2f} is EBITDA-linked operating leakage and SAR {recurring_h2 - recurring_h2_ebitda:,.2f} is treasury/FX exposure below the EBITDA bridge."
        )
        lines.append("")
        lines.append("Recurring patterns: " + '; '.join(
            f"{finding.finding_id}: {finding.title}: SAR {finding.recoverable_sar:,.2f} H1 exposure and SAR {finding.recoverable_sar:,.2f} projected H2 exposure unless fixed. [{_citation_list(finding.citations, limit=3)}]"
            for finding in recurring))
    else:
        lines.append("No recurring exposure classified by current deterministic run.")
    if non_recurring:
        lines.append("One-time / non-run-rate items: " + '; '.join(
            f"{finding.finding_id}: {finding.title}: SAR {finding.recoverable_sar:,.2f} recovery opportunity, but projected H2 recurring exposure = SAR 0.00 under the current classification. [{_citation_list(finding.citations, limit=2)}]"
            for finding in non_recurring))
    unconfirmed = [finding for finding in findings if finding.leakage_sar > 0 and finding.recoverable_sar == 0]
    if unconfirmed:
        lines.append("Recovery and future exposure remain unconfirmed: " + '; '.join(
            f"{finding.finding_id}: {finding.title}: SAR {finding.leakage_sar:,.2f} historical avoidable cost; no refund or H2 amount is established by these records. [{_citation_list(finding.citations, limit=2)}]"
            for finding in unconfirmed))
    return "\n".join(lines)


def _single_event_leakage_sar(finding: Finding) -> float:
    calculation = finding.calculation or {}
    if finding.pattern_type == "auto_renewal_escalation":
        current = float(calculation.get("current_monthly_fee_sar", 0.0))
        base = float(calculation.get("base_fee_sar", 0.0))
        return max(current - base, 0.0)
    if finding.pattern_type == "dormant_credit_balance":
        return float(calculation.get("credit_sar", finding.recoverable_sar))
    if finding.pattern_type == "duplicate_payment":
        return float(calculation.get("amount_sar", finding.recoverable_sar))
    if finding.pattern_type == "fx_hedge_unapplied":
        return float(calculation.get("exposure_sar", finding.recoverable_sar))
    if finding.pattern_type == "price_variance":
        return float(calculation.get("excess_sar", finding.recoverable_sar))
    return float(finding.recoverable_sar)


def _finding_affects_ebitda(finding: Finding) -> bool:
    return finding.pattern_type in {
        "auto_renewal_escalation",
        "duplicate_payment",
        "missed_early_pay_discount",
        "price_variance",
    }


def _impact_label(finding: Finding) -> str:
    if _finding_affects_ebitda(finding):
        return "EBITDA-linked"
    if finding.pattern_type == "fx_hedge_unapplied":
        return "cash / FX exposure"
    if finding.pattern_type == "entity_resolution_duplicate":
        return "control-dependent recovery"
    return "cash-only recovery"


def _citation_list(citations, *, limit: int) -> str:
    if not citations:
        return "no direct citation attached"
    return "; ".join(f"{citation.source_path} - {citation.locator}" for citation in citations[:limit])


def _detector_report(bundle: DataBundle) -> dict[str, list[dict[str, object]]]:
    report = bundle.detector_report or {}
    executed = report.get("executed_detectors") or []
    skipped = report.get("skipped_detectors") or []
    return {
        "executed_detectors": executed,
        "skipped_detectors": skipped,
    }


def _detector_summary(bundle: DataBundle) -> str:
    report = _detector_report(bundle)
    executed = report["executed_detectors"]
    skipped = report["skipped_detectors"]
    total = len(executed) + len(skipped)
    if total == 0:
        return "Detector execution coverage was not recorded in this report."
    if not skipped:
        return f"{len(executed)}/{max(total, len(executed))} detectors executed; no detectors were skipped."
    return f"{len(executed)}/{total} detectors executed; {len(skipped)} skipped due to missing required roles."


def _skipped_detector_lines(bundle: DataBundle) -> list[str]:
    report = _detector_report(bundle)
    lines: list[str] = []
    for item in report["skipped_detectors"]:
        lines.append(
            f"{item['detector']} ({item['pattern_type']}) skipped; required_roles={item['required_roles']}; missing_roles={item['missing_roles']}."
        )
    return lines


def _render_detector_coverage(bundle: DataBundle) -> list[str]:
    report = _detector_report(bundle)
    lines = ["## Detector Coverage", "", f"- {_detector_summary(bundle)}"]
    for item in report["executed_detectors"]:
        lines.append(
            f"- {item['detector']} ({item['pattern_type']}): executed; required_roles={item['required_roles']}; findings={item['finding_count']}"
        )
    for item in report["skipped_detectors"]:
        lines.append(
            f"- {item['detector']} ({item['pattern_type']}): skipped; required_roles={item['required_roles']}; missing_roles={item['missing_roles']}"
        )
    lines.append("")
    return lines


def _ebitda_inputs_available(bundle: DataBundle) -> bool:
    """EBITDA bridge needs trial balance, chart of accounts, and GL together."""
    available = (bundle.run_metadata or {}).get('available_roles')
    if available is not None and not {'trial_balance', 'chart_of_accounts', 'gl_extract'}.issubset(available):
        return False
    for frame, columns in (
        (bundle.trial_balance, ("Account", "Credit_Total", "Debit_Total")),
        (bundle.coa, ("Account", "Account_Description", "Type")),
        (bundle.gl, ("Account", "Debit", "Credit")),
    ):
        if frame is None or frame.empty:
            return False
        if any(column not in frame.columns for column in columns):
            return False
    return True


def _compute_ebitda_baseline(bundle: DataBundle) -> dict:
    if not _ebitda_inputs_available(bundle):
        return {"available": False, "reason": "The GL, trial balance and account classification are required."}

    def account(value):
        text = str(value).strip()
        return text[:-2] if text.endswith('.0') else text

    def money(value):
        result = Decimal(str(value).replace(',', '').strip())
        if not result.is_finite():
            raise ValueError('Non-finite financial value')
        return result

    from ..evidence import sha256_file
    citations = []
    for role, frame in [('trial_balance', bundle.trial_balance), ('chart_of_accounts', bundle.coa), ('gl_extract', bundle.gl)]:
        path = _role_source_path(bundle, role)
        expected = bundle.evidence.hash_for(path)
        source = bundle.dataset_root / path
        if not expected or not source.is_file() or sha256_file(source) != expected:
            return {'available': False, 'reason': 'A baseline source changed or has no verified evidence hash.'}
        citations.append({'source_path': path, 'locator': f'rows 2–{len(frame) + 1}', 'sha256': expected})

    coa = {}
    for _, row in bundle.coa.iterrows():
        key = account(row['Account'])
        if not key or key in coa:
            return {'available': False, 'reason': 'Account classification keys are absent or duplicated.'}
        coa[key] = row
    trial, ledger = {}, {}
    try:
        for _, row in bundle.trial_balance.iterrows():
            key = account(row['Account'])
            if key in trial or key not in coa:
                return {'available': False, 'reason': 'Trial-balance account mapping is incomplete or duplicated.'}
            trial[key] = (money(row['Debit_Total']), money(row['Credit_Total']))
        for _, row in bundle.gl.iterrows():
            key = account(row['Account'])
            if key not in coa:
                return {'available': False, 'reason': 'A ledger account has no account classification.'}
            previous = ledger.get(key, (Decimal(0), Decimal(0)))
            ledger[key] = (previous[0] + money(row['Debit']), previous[1] + money(row['Credit']))
    except (ValueError, InvalidOperation):
        return {'available': False, 'reason': 'The baseline contains an invalid financial value.'}
    variance = max((abs(trial.get(key, (Decimal(0), Decimal(0)))[side] - ledger.get(key, (Decimal(0), Decimal(0)))[side])
                    for key in trial.keys() | ledger.keys() for side in (0, 1)), default=Decimal(0))
    if variance >= Decimal('.01'):
        return {'available': False, 'reason': 'The GL does not reconcile to the trial balance.',
                'gl_tb_reconciled': False, 'gl_tb_max_variance_sar': float(variance), 'citations': citations}
    revenue_sar = expense_total_sar = addbacks_sar = Decimal(0)
    exclusions = re.compile(r'\b(depreciation|amorti[sz]ation|interest|income tax|zakat)\b', re.I)
    for key, (debit, credit) in trial.items():
        kind = str(coa[key]['Type']).strip().casefold()
        if kind == 'revenue':
            revenue_sar += credit - debit
        elif kind == 'expense':
            expense_total_sar += debit - credit
            if exclusions.search(str(coa[key]['Account_Description'])):
                addbacks_sar += debit - credit
        elif kind not in {'asset', 'liability', 'equity'}:
            return {'available': False, 'reason': 'The account classification contains an unsupported type.'}
    if revenue_sar <= 0:
        return {'available': False, 'reason': 'A positive reconciled revenue denominator is required for the margin.'}
    baseline_ebitda_sar = revenue_sar - expense_total_sar + addbacks_sar
    return {
        "available": True,
        "revenue_sar": float(revenue_sar),
        "expense_total_sar": float(expense_total_sar),
        "addbacks_sar": float(addbacks_sar),
        "baseline_ebitda_sar": float(baseline_ebitda_sar),
        "baseline_margin": float(baseline_ebitda_sar / revenue_sar),
        "gl_tb_reconciled": True,
        "gl_tb_max_variance_sar": float(variance),
        "citations": citations,
    }


def _format_ebitda_citations(ebitda: dict) -> str:
    return '; '.join(f"{item['source_path']} - {item['locator']}" for item in ebitda.get('citations', [])) + (
        f"; account roll-up reconciles to TB with max variance SAR {ebitda['gl_tb_max_variance_sar']:,.2f}"
        if ebitda.get('gl_tb_reconciled') else '')


def write_markdown_pdf(markdown_text: str, output_path: Path, *, title: str) -> Path:
    from ..board_layout import fonts
    fonts()
    styles = getSampleStyleSheet()
    heading_1 = ParagraphStyle(
        "StrategyOSHeading1",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        keepWithNext=True,
        spaceAfter=10,
    )
    heading_2 = ParagraphStyle(
        "StrategyOSHeading2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        keepWithNext=True,
        spaceBefore=6,
        spaceAfter=6,
    )
    heading_3 = ParagraphStyle(
        "StrategyOSHeading3",
        parent=styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        keepWithNext=True,
        spaceBefore=4,
        spaceAfter=4,
    )
    body = ParagraphStyle(
        "StrategyOSBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        spaceAfter=4,
    )
    bullet = ParagraphStyle(
        "StrategyOSBullet",
        parent=body,
        leftIndent=12,
        firstLineIndent=0,
    )

    story = []
    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not line:
            # Heading styles already provide spacing. An intervening Spacer
            # breaks ReportLab's keepWithNext link to the first content line.
            if not story or not isinstance(story[-1], Paragraph) or not getattr(story[-1].style, 'keepWithNext', False):
                story.append(Spacer(1, 6))
            continue
        if line == '<!-- pagebreak -->':
            story.append(PageBreak())
            continue
        if line.startswith("# "):
            story.append(Paragraph(_escape_pdf_text(line[2:]), heading_1))
            continue
        if line.startswith("## "):
            story.append(Paragraph(_escape_pdf_text(line[3:]), heading_2))
            continue
        if line.startswith("### "):
            story.append(Paragraph(_escape_pdf_text(line[4:]), heading_3))
            continue
        if line.startswith("- "):
            story.append(Paragraph(_escape_pdf_text(line[2:]), bullet, bulletText='•'))
            continue
        if line.startswith('> '):
            story.append(Paragraph(_escape_pdf_text(line[2:]), bullet))
            continue
        story.append(Paragraph(_escape_pdf_text(line), body))

    document = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        title=title,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    document.build(story)
    return output_path


def _escape_pdf_text(value: str) -> str:
    from ..board_layout import fonts
    from ..board_pack import visual
    arabic = fonts().getFont('BoardArabic').face.charToGlyph
    # Source excerpts can contain Arabic even in an English case file. Embed
    # the same licensed fonts used by board packs instead of losing glyphs.
    runs: list[tuple[str | None, str]] = []
    # Shape Arabic spans without moving surrounding source punctuation or
    # identifiers across a paragraph's Latin text.
    display_value = re.sub(r'[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]+(?:\s+[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]+)*',
                           lambda match: visual(match.group()), value)
    for char in display_value:
        font = ('BoardArabic' if ord(char) in arabic else 'BoardLatin') if ord(char) > 255 else None
        if runs and runs[-1][0] == font:
            runs[-1] = (font, runs[-1][1] + char)
        else:
            runs.append((font, char))
    result = []
    for font, text in runs:
        escaped = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        result.append(f'<font name="{font}">{escaped}</font>' if font else escaped)
    return ''.join(result)
