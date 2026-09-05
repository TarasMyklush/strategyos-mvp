# StrategyOS Codex subscription provider

Matches WebAgents/Northstar's `codex_cli` approach: the official Codex CLI uses
ChatGPT login, with no explicit model override by default. `codex-subscription`
is a routing label, **not a model name**. Account availability and CLI defaults
determine the underlying model. Subscription quotas still apply.

## Boundary

Hermes and specialist reasoning retain their existing OpenAI-compatible transport,
evidence assembly, run-policy checks, citations, deterministic calculations and
action approval gates. A private provider service translates text-only requests
to `codex exec`. Neither the API nor worker receives the subscription login.
There is no automatic DeepSeek fallback or new authority to execute actions.
The background worker previously had LLM access disabled. Its provider routing
is updated, but that policy remains disabled; the acceptance check verifies the
restriction rather than enabling model access to satisfy a test. Specialist
reasoning already authorized in the API continues through the new provider.

The provider has its own unprivileged container, authentication home, temporary
request directories, a private API network, and egress for Codex. It has no public
port, business-data mount, database network or Docker socket. It ignores Codex
user/project configuration and rules, disables action tools/plugins/MCP/web search,
uses read-only sandboxing and ephemeral sessions, strips application credentials
from the child environment, and returns only the final answer. Approval is never
delegated to the model. One request can execute at a time; a busy runner returns
429. A 120-second deadline kills the process group; the client timeout is 135s.

No shell-sandbox bypass or unconfined container permissions are required.
The pinned CLI version is 0.149.0, matching the inspected WebAgents deployment.
The Docker image digest, not its mutable tag, should be used for releases.

## Preview deployment, production promotion, and rollback

The `StrategyOS Codex Provider Preview` workflow tests and builds the provider,
then changes **only** the provider routing for `new.strategyos.live`. It retains
the exact currently running API and worker images; no UI, dataset or database
release is bundled with this change. Production `strategyos.live` is untouched.

Production promotion is a separate, manually dispatched `StrategyOS Codex
Provider Production` workflow, added after the user's explicit production
authorization. It verifies preview acceptance and promotes the exact tested
provider image digest, without rebuilding it or deploying a new app image.
It uses the same isolated setup under `/opt/strategyos/provider-codex`. The
deployment tool defaults to preview; production requires `--target production`.
Both environments run live probes before switching and authenticated application
checks afterward. Failed checks roll back provider routing.
The production workflow uses the existing live-server GitHub environment named
`hetzner-qa` (a legacy label), not the `hetzner-branch` preview credentials.

Host-managed files live in `/opt/strategyos-branch/provider-codex`, outside release
syncs. The deployment owner provisions `auth/auth.json` using a Codex ChatGPT login.
On initial installation only, the owner's explicit `--auth-source` can bootstrap
from their existing WebAgents login on the same host. No auth material is copied
to the workstation, GitHub, logs, application containers, or repository. Subsequent
deployments retain that dedicated login; WebAgents' authentication is not modified.

If the dedicated login expires, reauthenticate that provider; do not repeatedly
overwrite it from another service. Token rotation can require a fresh login.
The provider's `/healthz` is **liveness only**; use an authenticated completion
probe to verify actual subscription access and remaining capacity.

Deployment modes in `deploy/scripts/manage_codex_provider.py`:

- `prepare --image <digest> --overlay <reviewed-compose-path>`: start provider only.
- `activate`: recreate preview API/worker with provider overrides after smoke tests.
- `rollback`: restore the original provider configuration, without changing app
  images or business data. Credentials are retained for recovery, not deleted.

Existing full-app deployments load this overlay only when its host `enabled`
marker exists. Removing/renaming the marker disables it for future releases;
use `rollback` to revert currently running containers immediately.

## Verification

`python -m pytest tests/test_codex_gateway.py tests/test_llm_qa.py
tests/test_deterministic_vs_llm_boundary.py` tests request validation, role/history
preservation, environment stripping, denied tool capabilities, queue saturation,
timeouts, response contracts, and unchanged deterministic/governed routing.
Live probes must additionally cover a structured response, context follow-up,
an unsupported business claim, and a hostile command/credential request. Inspect
API/worker provider settings and authenticate a real Hermes request after activation.

Official interface: https://developers.openai.com/codex/noninteractive/
Security reference: https://developers.openai.com/codex/security/
