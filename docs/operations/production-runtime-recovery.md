# Production runtime and release acceptance

The delivery target is `https://strategyos.live`, Compose project `strategyos`,
under `/opt/strategyos`. The preview database and dataset are independent.

The production deploy now creates and checks a custom-format PostgreSQL backup,
runs the release's complete migration module, and provisions separate
`strategyos_production_runtime`, `strategyos_production_worker` and
`strategyos_production_projector` logins. Runtime processes verify the schema;
they cannot perform migrations. Credentials stay in the private host file
`/opt/strategyos/runtime-database/runtime.env`, outside release syncs.

All effective runtime connections are checked against the migration database
target before starting the release. The public URL must be explicitly configured
as `https://strategyos.live` so browser session writes survive TLS termination.
Provider activation must preserve the same database role file. The shared SQL
capability markers retain their historical `preview` names; production uses
distinct login roles in its own database.

Automatic rollback to arbitrary legacy application directories is disabled:
such images may disagree with the migration fingerprint or regain database-owner
authority. Recover with a tested release compatible with the current schema.
Database backups and prior images are retained; routine deployment never prunes
the shared Docker host.

The application image pins its Python base digest and uses a dated Debian
snapshot for its exact OS package versions. Moving Debian mirrors remove old
versions and can make unchanged releases unbuildable. Update the snapshot,
base digest and affected version pins together for security maintenance;
repository signatures remain verified even when snapshot expiry is disabled.

Release acceptance includes the actual customer briefing, 576-cell Intent plan,
granular analysis, persona navigation, mobile view, and real Hermes questions
with source labels and evidence links. Research alone is insufficient. These
walkthroughs are for the supplied synthetic POC; test ratification is recorded
as synthetic acceptance, never represented as an actual board decision.

The Codex provider uses Sol with medium reasoning. Its liveness endpoint does
not prove subscription authentication: real model/browser checks must pass.
If the dedicated production refresh token is expired or reused, obtain a new
device login in the production gateway. Do not copy a refresh token shared with
another CLI installation, or claim that a healthy container means chat works.
