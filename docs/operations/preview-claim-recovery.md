# Preview source-and-claim recovery

Scope: `/opt/strategyos-branch`, `new.strategyos.live`, Compose project
`strategyos-branch`. This does not change the production rollout policy.

Once a deployment has been attempted, a failed rollout or post-deploy gate must
not automatically start an older application against newer claim and audit data.
The preview workflow therefore quiesces only its API, worker and claim projector
containers. Every selected container's project and service labels are checked
again before stopping it. No database, index, object store, identity provider,
volume or backup is removed or replaced. The ordinary rollback helper refuses
this preview target too.

This deliberately trades availability for a fail-closed state. The public edge
may return an upstream-unavailable response until recovery. Do not interpret a
successful quiesce as a successful release; the failed workflow stays failed.

Recovery is a **roll-forward** through the same preview workflow:

1. Inspect the failed gate and stopped preview services, retaining its logs.
2. Keep the database archive and all newly recorded revisions/assessments intact.
3. Fix the release in the feature branch and pass the complete service suite.
4. Deploy a verified compatible release. Additive schema migrations must remain
   compatible with the persisted ledger; never edit a previously applied migration.
5. Repeat protected readiness, public edge, cross-role and human-browser checks.

A database restore is a separate, explicitly authorized incident operation, not
an automatic application rollback. Rehearse restores on isolated databases and
account for any post-backup revisions before proposing a restore. This document
does not authorize deleting evidence or choosing an erasure/retention policy.

Tests exercise the actual remote shell body with a Docker double, including
multiple projector replicas and rejection of a foreign ownership label. They do
not stop the live preview to manufacture a recovery demonstration. A real
availability-impacting failure drill remains separately scheduled.
