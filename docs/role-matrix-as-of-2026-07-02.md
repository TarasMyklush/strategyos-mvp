# StrategyOS Role Matrix — as of 2026-07-02

Based on the live deployed app `/ui/session` capabilities plus the current source role hierarchy.

## Simple operating model

- **Operator / Tenant Operator:** upload data, validate source packs, launch runs, manage ingestion.
- **Reviewer / Auditor:** review evidence/findings, approve/reject/claim review work.
- **Analyst:** investigate evidence/cases, but does not approve final workflow.
- **BU:** business-unit stakeholder; reviews cases and evidence QA, but does not investigate deeply or approve workflow.
- **Executive:** consumes board/executive surface; should not operate/review raw workflow.
- **Tenant Admin / System:** admin/superuser; can do almost everything, including runtime/system visibility.

## Role matrix

### operator

**Can:**
- View overview and cases.
- Investigate evidence.
- Review workflow.
- Launch runs.
- Manage ingestion/source packs.
- View runtime.
- Switch company/portfolio.
- View evidence QA.

**Should do:**
- Upload source packs.
- Validate dataset readiness.
- Launch StrategyOS runs.
- Monitor run/job status.
- Resume operational runs if needed.
- Coordinate with reviewer when a run pauses at `awaiting_review`.

**Current app routes:**
- `/app?lane=operate`
- `POST /source-packs`
- `POST /source-packs/from-path`
- `POST /source-packs/validate`
- `POST /source-packs/confirm-mapping`
- `GET /ingestion/connectors`
- `POST /runs`

---

### reviewer

**Can:**
- View overview and cases.
- Investigate evidence.
- Review workflow.
- View runtime.
- Switch company/portfolio.
- View evidence QA.
- Cannot launch runs.
- Cannot manage ingestion.

**Should do:**
- Review findings after a run pauses.
- Claim review items.
- Approve/reject run findings.
- Validate evidence quality and citation sufficiency.
- Decide whether the workflow can proceed to writer/final deliverables.

**Current app routes:**
- `/app?lane=review#review`
- `/reviewer/pending-reviews`
- `/reviewer/runs/{run_id}/claim`
- `/reviewer/runs/{run_id}/approve`
- `/reviewer/runs/{run_id}/reject`
- `/runs/latest/findings?domain=evidence_qa`

---

### bu

**Can:**
- View overview and cases.
- View evidence QA.
- Switch company/portfolio.
- Cannot investigate evidence.
- Cannot review/approve workflow.
- Cannot launch runs.
- Cannot manage ingestion.
- Cannot view runtime.

**Should do:**
- Business-side review of cases.
- Confirm whether findings make business sense.
- Review BU-level pending items.
- Provide business feedback, not technical approval.

**Current app routes:**
- `/app?lane=review#bu`
- `/bu/pending-reviews`
- `/bu/runs/{run_id}`
- `/runs/latest/findings?domain=finance_integrity`
- `/runs/latest/findings?domain=evidence_qa`

---

### analyst

**Can:**
- View overview and cases.
- Investigate evidence.
- View runtime.
- Switch company/portfolio.
- Cannot review/approve workflow.
- Cannot launch runs.
- Cannot manage ingestion.
- Cannot view evidence QA per current live capability flag.

**Should do:**
- Drill into evidence and cases.
- Investigate anomalies.
- Support reviewer/operator with analysis.
- Explore findings, citations, graph, and financial signals.
- Not make approval decisions.

---

### auditor

**Can:**
- View overview and cases.
- Investigate evidence.
- Review workflow.
- View runtime.
- Switch company/portfolio.
- View evidence QA.
- Cannot launch runs.
- Cannot manage ingestion.

**Why:** `auditor` inherits `reviewer` in the platform role hierarchy.

**Should do:**
- Challenge findings.
- Validate citation integrity.
- Review audit trail and evidence QA.
- Approve/reject from an audit-control perspective.
- Focus on whether findings are defensible.

---

### executive

**Can:**
- View overview and cases.
- View runtime.
- Switch company/portfolio.
- Uses `/executive` landing page.
- Cannot investigate evidence.
- Cannot review/approve workflow.
- Cannot launch runs.
- Cannot manage ingestion.
- Cannot view evidence QA.

**Should do:**
- Consume executive/board-safe summary.
- Review high-level findings, business impact, and decision points.
- Use CEO/board personas.
- Not operate workflow or inspect raw evidence.

**Current app surface:**
- `/executive`
- Executive personas:
  - `ceo`
  - `cfo`
  - `gm`
  - `bucfo`
  - `logistics`
  - `board`

---

### tenant_operator

**Can:**
- Everything operator can do.
- Also inherits analyst capability.
- Launch runs.
- Manage ingestion.
- Investigate evidence.
- Review workflow.
- View runtime.
- Switch company/portfolio.
- View evidence QA.

**Should do:**
- Tenant-level operational execution.
- Upload/validate/run datasets for the tenant.
- Manage source-pack workflow.
- Troubleshoot tenant ingestion/run issues.
- Escalate admin/system issues to tenant admin/system.

---

### tenant_admin

**Can:**
- Broad admin/superuser capabilities.
- View overview/cases.
- Investigate evidence.
- Review workflow.
- Launch runs.
- Manage ingestion.
- View runtime/system endpoints.
- Switch company/portfolio.
- View evidence QA.
- Access run-job status endpoint.

**Should do:**
- Tenant administration.
- Runtime/config visibility.
- Connector governance.
- Review queues oversight.
- Health/dependency checks.
- Troubleshoot stuck jobs/runs.

**Current app routes:**
- `/app?lane=system`
- `/ingestion/connectors`
- `/data/status`
- `/runs/latest/report-preview`
- `/reviewer/pending-reviews`
- `/bu/pending-reviews`
- `/health/ready`
- `/health/config`
- `/health/dependencies`
- `/runs/jobs/{job_id}`

---

### system

**Can:**
- Full system/superuser capabilities.
- Inherits tenant admin, tenant operator, operator, reviewer, analyst, auditor, executive.
- Can launch/manage/review/investigate/view runtime.

**Should do:**
- Automation/service operations.
- System health and runtime checks.
- Background worker/job supervision.
- Integration-level troubleshooting.
- Not be used as normal human testing role unless testing admin/system boundaries.

## Twin dashboard access

- **CEO twin**
  - Roles: `executive`, `tenant_admin`, `system`

- **CFO twin**
  - Roles: `operator`, `reviewer`, `tenant_admin`, `system`

- **Group Manager twin**
  - Roles: `bu`, `operator`, `tenant_operator`, `tenant_admin`, `system`

- **Sensitive twin diagnostics**
  - Roles: `tenant_admin`, `system`

## Current uploaded dataset workflow status

For the currently uploaded synthetic dataset:

- Operator uploaded it.
- App accepted and validated it.
- Run succeeded.
- Run is now:
  - `awaiting_review`
  - `requires_human_review: true`
  - `review_state: awaiting_decision`

## Next correct human step

1. **Reviewer or Auditor** reviews the run.
2. They approve/reject/challenge findings.
3. If approved, workflow can proceed to writer/final deliverables.
4. Executive consumes the safe summary after review, not before.
