"""Render the readable assessment from its canonical JSON register."""
from pathlib import Path
import json
import os

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "docs/assessment"


def render() -> None:
    data = json.loads((FOLDER / "gap-register.json").read_text())
    gaps = data["gaps"]
    counts = {priority: sum(g["priority"] == priority for g in gaps) for priority in ["P0", "P1", "P2"]}
    assert counts == data["counts"], "Update counts with the gap register"
    partial = sum(g.get("closure_status") == "partial" for g in gaps)
    closed = sum(g.get("closure_status") == "closed" for g in gaps)
    lines = [
        "# StrategyOS gap analysis", "",
        f"Assessment date: {data['assessment_date']}. Reviewed baseline: `{data['baseline']}`.", "",
        "The preview now runs the enriched approved synthetic dataset with durable review state, scoped local semantic retrieval, immutable board records and encrypted inference audit. The register below separates verified corrections from incomplete acceptance. It does not claim a complete enterprise product or a passed factual assistant gate.", "",
        f"The register contains **{len(gaps)} gaps: {counts['P0']} P0, {counts['P1']} P1 and {counts['P2']} P2**. {partial} have partial remediation and {closed} are closed. These are risk priorities, not a completion percentage.", "",
        "## Current scope", "",
        data.get("remediation_scope", "See canonical requirements."), "",
        data.get("ui_constraint", "Preserve the existing interface."), "",
        "[Current validation](validation.md) and the [preview release receipt](evidence/preview-release.json) identify tested behavior and the deployed code/data combination. Historical evidence below is retained for traceability, not as the current deployment status.", "",
        "## Original assessment and validation limits", "",
        "The baseline assessment compared main `9fa5316` and candidate `c03e958`, inspected requirements, ran portable tests, reproduced targeted defects offline and sampled authenticated preview behavior. The live executive JavaScript matched the candidate; the backend image was not attested. The selected preview run awaited review and lacked enriched strategy/calendar/plan data. Logout returned 404 and the session could still read a protected run. No approval, upload, deployment, board-close mutation or destructive live security test was performed.", "",
        "Baseline testing recorded 1,569 passes, 77 skips and one harness-path failure, followed by 10 passing configuration tests after correcting the harness path. [Current validation](validation.md) records consolidation results. Portable tests do not establish service integration, factual assistant acceptance or operational certification. Immutable source links preserve the reviewed evidence after local cleanup.", "",
        "The [canonical specification](../requirements.md) resolves earlier requirement conflicts. This report is generated from [gap-register.json](gap-register.json); update the register and run `python scripts/render_gap_analysis.py` instead of editing this file.", "",
        "## Prioritized register", "", "| ID | Priority | Area | Gap | Closure |", "|---|---|---|---|---|",
    ]
    for gap in gaps:
        lines.append(f"| [{gap['id']}](#{gap['id'].lower()}) | {gap['priority']} | {gap['domain']} | {gap['title']} | {gap.get('closure_status', 'open')} |")
    for gap in gaps:
        lines += ["", f'<a id="{gap["id"].lower()}"></a>', f"## {gap['id']} · {gap['priority']} · {gap['title']}", ""]
        for label, key in [("Current position", "observation"), ("Impact", "impact"), ("Required work", "action"), ("Acceptance", "acceptance"), ("Suggested owner", "suggested_owner"), ("Evidence classification", "status")]:
            lines += [f"**{label}:** {gap[key]}", ""]
        refs = []
        for ref in gap["evidence"]:
            path = ref["path"]
            target = path if path.startswith("https:") else os.path.relpath(ROOT / path, FOLDER)
            refs.append(f"[{ref['label']}](<{target}>)")
        lines.append("**Evidence:** " + "; ".join(refs) + ".")
    (FOLDER / "gap-analysis.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    render()
