# StrategyOS Chat + Dashboard UI — Implementation Plan

**Date:** 2026-06-12
**Status:** Approved design, ready to implement
**Visual reference:** `docs/chat-dashboard-ui-mockup.html` (open in a browser — this is the target look)
**Audience:** any developer or LLM agent implementing this cold. Everything needed is in this file plus the mockup; verify claims against the code before relying on them, and update this doc if you find drift.

---

## 1. Goal

Replace the current form-wall dashboard with a two-zone UI:

1. **Dashboard strip (top):** compact metric cards and status chips for the latest run — recoverable SAR, findings count, citation resolution, auditor challenges, stage stepper, store sync badges (postgres / neo4j / qdrant), run mode (full/partial).
2. **Chat surface (main):** an evidence-grounded Q&A thread driven by the existing deterministic `POST /qa` endpoint. Answer bubbles show the value, the basis line, and clickable citation chips. System messages narrate run lifecycle events (run completed, auditor challenged N findings, awaiting review). When a run pauses for human review, the approve/reject actions appear as an actionable system message in the thread.

Secondary flows (upload source pack → confirm column mapping → start run) move into a slide-over panel opened from a "New run" header button. They keep their existing behavior.

## 2. Context a cold implementer needs

- **Repo:** `strategyos_mvp` (Python 3.14, FastAPI). Run tests: `.venv/bin/python -m pytest -q`. Full suite must stay green (167 passed / 1 skipped baseline as of 2026-06-12; the skip is a Postgres e2e gated on an env var).
- **Where the UI lives today:** the ENTIRE frontend is inline Python strings in `strategyos_mvp/api.py` (~3,800 lines total; the HTML/CSS/JS shell is roughly lines 900–3350, served by `GET /` at `api.py:3347`). There is no `static/` directory and no build toolchain.
- **Auth model:** bearer tokens from the local IDP. The current shell stores the token in `localStorage` under key `strategyos.ui.token` (`api.py:1517,3101`). Token acquisition: `POST {idp}/oauth/token` with form-encoded `grant_type=password&client_id=...&client_secret=...&username=...&password=...`. A `GET /ui/session` endpoint reports the authenticated role (see `tests/test_frontend_shell.py:253,275`). All data endpoints require `Authorization: Bearer <token>` (or `X-API-Key` in non-IDP mode).
- **Test trap #1:** `tests/test_frontend_shell.py` has 15 tests asserting specific element ids/hooks exist in the HTML served at `GET /` (queue shell, bootstrap JSON, run detail, review console, runs index, queue assignment, artifact inspector, data status console, vector search panel, **qa panel**, start-run form, source-pack intake, health console, ui-session behavior). Any redesign must either preserve those hooks or **deliberately update the tests in the same commit** — never delete assertions without replacing them with equivalents for the new UI.
- **Test trap #2:** one shell test asserts the page **embeds parseable bootstrap JSON** (`test_dashboard_embeds_parseable_bootstrap_json`). Keep server-side bootstrap injection (see Phase 1 §4.3).
- **Deployment constraint:** the app deploys to a VPN-only Azure QA VM behind Caddy (`deploy/README.md`). All assets must be served by the app itself — **no CDN links, no external fonts, no node toolchain**. Vanilla HTML/CSS/JS only.

## 3. Hard constraints

1. **No LLM.** `POST /qa` is deterministic (keyword/intent matching in `strategyos_mvp/qa.py`). The UI must present it honestly: placeholder text describing what it can answer, suggestion chips, and a graceful unmatched state. Do not fake open-ended conversation.
2. **No new backend business logic for v1.** Every UI element binds to an endpoint that already exists (§4). Small additive endpoints are allowed only if listed in §6.
3. **Backward compatibility:** existing endpoints keep their paths and response shapes. The reviewer/operator API is used by scripts and tests.
4. **All assets local.** No external origins anywhere in the served HTML.
5. **Auth preserved:** every fetch sends the bearer token; 401 ⇒ show the sign-in panel, never an unstyled error.

## 4. API contract reference (verified 2026-06-12)

### 4.1 `POST /qa` — the chat engine
Request: `{"question": str, "run_id": str|null}` (omit `run_id` ⇒ latest run).
Response (success): top-level `{"status":"ok","run_id":...,"run_mode":"full|partial","question":...}` merged with the engine result:
- `matched: bool` — `false` ⇒ render the "can't answer that" bubble using `suggestions`
- `answer: str` — human-readable sentence (always present)
- `value: number|null`, `unit: str|null` — for the big-number rendering in the bubble
- `basis: str` — one-line provenance ("how this was computed") — render muted under the answer
- `intent: str` — matched intent name (render as a tiny tag, useful for debugging)
- `citations: [{source_path, locator, excerpt}]` — render as chips: filename tail + locator; click ⇒ expandable excerpt
- `suggestions: [str]` — present when unmatched; render as clickable chips that fill the input
- For partial runs, a missing role yields `available: false` with an explanatory `answer` — render normally.

### 4.2 `GET /runs/latest` — feeds the dashboard strip
Returns the run summary dict (or `{"status":"missing"}` ⇒ render empty state "No runs yet — start one"). Fields used by the UI:
- `total_recoverable_sar: float` → "recoverable" card (format with thousands separators)
- `findings: int`, `locked_findings: int` → "findings" card
- `status` (`completed|running|awaiting_review|failed`), `current_stage` → stage stepper. Stage order: `ingest → analyst → auditor → evidence_qa → knowledge_graph → awaiting_review? → writer`. Pull the live stage list from the `pipeline` key in `runtime` metadata if present rather than hard-coding.
- `requires_human_review: bool`, `approval_status` → review banner / approve-reject chat message
- `run_mode: "full"|"partial"`, `available_roles`, `missing_roles`, `detector_report.skipped_detectors[{detector,reason}]` → partial-run chips ("Skipped: price_variance — purchase_orders missing")
- `state_store.status`, `neo4j.status`, `qdrant.status` (`persisted/synced/skipped`) → store badges (green=synced/persisted, amber=skipped + reason on hover)
- `audit_event_count: int` and the ping-pong audit log artifact path under `artifacts` → "challenged by auditor" card (count of distinct challenged finding ids; if you need it as JSON, read `artifacts.audit_log`; if fetching artifact files turns out awkward, an additive `GET /runs/latest/audit-summary` endpoint is permitted per §6)
- Citation numbers: the citation audit JSON path is in `artifacts.citation_audit` (`summary.citation_count`, `summary.resolved_count`). Same additive-endpoint escape hatch applies.

### 4.3 Other endpoints used as-is
- `GET /data/status` — backing-store detail console (keep, move to a "System" drawer)
- `GET /ui/session` — `{authenticated, role, ...}` for header identity
- `POST /runs` — start run `{"skip_prepare":true,"sync_artifacts":true,"source_pack_id":...}`; 400 lists `unconfirmed_roles`
- `POST /source-packs` (multipart upload), `POST /source-packs/from-path`, `POST /source-packs/validate`, `POST /source-packs/confirm-mapping` — the existing intake + mapping-confirmation flow; reuse the current JS logic for the slide-over
- `GET /reviewer/pending-reviews`, `POST /reviewer/runs/{id}/approve`, `POST /reviewer/runs/{id}/reject`, `POST /operator/runs/{id}/resume` — the review actions surfaced as chat-message buttons
- `GET /health/live`, `/health/ready`, `/health/dependencies` — "System" drawer

## 5. Phase 1 — extract the frontend to static files (do this first, no visual changes)

1. Create `strategyos_mvp/static/` with `index.html`, `app.js`, `styles.css`. Move the inline shell out of `api.py` verbatim.
2. **Un-escape the f-string braces.** The current HTML/JS lives inside Python f-strings, so every literal `{` is written `{{`. When moving to real files, convert `{{`→`{` and `}}`→`}` everywhere EXCEPT the bootstrap placeholder (next item). Mechanical but error-prone — diff the served bytes before/after (see verification).
3. **Bootstrap JSON:** keep `GET /` as a FastAPI handler that reads `static/index.html` and substitutes a single `__STRATEGYOS_BOOTSTRAP__` placeholder with the JSON the shell currently embeds. Mount `app.js`/`styles.css` via `StaticFiles` at `/static`. This keeps `test_dashboard_embeds_parseable_bootstrap_json` green.
4. Add the static dir to the package build (`pyproject.toml` package data) and to the Docker image (check `deploy/Dockerfile` copies it).
5. **Verification:** all 15 `test_frontend_shell.py` tests green unmodified; `GET /` byte-diff vs pre-refactor differs only in asset URLs; manual smoke: login, start fixture run, Q&A panel answers.

Exit: `api.py` drops to roughly a third of its size; no behavior change.

## 6. Phase 2 — build the chat + dashboard view

Component inventory (all in vanilla JS; one `app.js` module pattern is fine):

| Component | Data source | Notes |
| --- | --- | --- |
| Header (app name, run id pill, identity, "New run" button) | `/runs/latest`, `/ui/session` | pill color: green completed, blue running, amber awaiting review, red failed |
| KPI cards ×4 (recoverable, findings, citations resolved, challenged) | `/runs/latest` + citation/audit summaries | numbers via `toLocaleString()`; citations green only at 100% |
| Stage stepper | `/runs/latest.current_stage` | completed stages get a check; `awaiting_review` renders only when `requires_human_review` |
| Store badges | `state_store/neo4j/qdrant.status` | tooltip shows skip reason |
| Partial-run chips | `run_mode`, `missing_roles`, `skipped_detectors` | hidden on full runs |
| Chat thread | client-side array; answers from `POST /qa` | persist thread per run id in `sessionStorage`; **no server-side chat memory — each question is independent** (deterministic engine) |
| System messages | derived on poll: status transitions of `/runs/latest` | e.g. on `completed`: "Run completed — N findings locked, SAR X recoverable" |
| Review action message | `requires_human_review && approval_status=="pending"` | Approve/Reject buttons → reviewer endpoints → then operator resume button |
| Suggestion chips | `suggestions` from unmatched `/qa` + a static starter set | starter set: copy the curated intents from `qa.py` `SUGGESTIONS` |
| Citation chips + excerpt expander | `citations[]` on each answer | chip label: `basename(source_path) · locator`; click toggles the guarded excerpt text |
| New-run slide-over | existing source-pack JS flow | reuse Phase-1-extracted logic; includes upload, validate, per-column mapping table (`#source-pack-mappings` hooks), task readiness, start button |
| System drawer | `/data/status`, `/health/*` | parks the old consoles (artifact inspector, vector search) without redesigning them |
| Sign-in panel | IDP token flow | shown on 401/no token; stores to `strategyos.ui.token` |

Polling: `GET /runs/latest` every 5s while `status=="running"` or `awaiting_review`, every 30s otherwise; pause when tab hidden (`document.visibilityState`).

Permitted additive backend work (only if needed): `GET /runs/latest/audit-summary` returning `{challenged_finding_ids, citation_count, resolved_count}` assembled server-side from the artifacts — keeps the UI from parsing artifact files.

Design tokens (match the mockup): neutral surfaces, one accent — teal `#0F6E56` on `#E1F5EE` for user bubbles/identity chips; semantic green/amber for store badges; system font stack; 12px label / 14px body / 21px metric numbers; 0.5px borders `#e3e6ea`; 12px radius cards, 999px pills. Dark mode is out of scope for v1.

## 7. Testing & acceptance

1. **Update `tests/test_frontend_shell.py` deliberately:** map each old slice assertion to its new home (qa panel → chat thread hooks `#chat-thread`/`#chat-input`; start-run form → slide-over hooks; consoles → system drawer hooks). Keep: bootstrap JSON, ui-session, source-pack intake hooks, review console (now chat-message buttons — assert the hook ids).
2. **New tests:** KPI card ids present with bootstrap-bound values; chat unmatched state renders suggestions; review buttons present when bootstrap says `requires_human_review`; no external origins in served HTML (`assert "https://cdn" not in html` and similar).
3. **Suite:** full `pytest -q` green; `make poc-acceptance` untouched (backend unchanged).
4. **Manual acceptance:** login → ask the 4 starter questions → answers carry ≥1 citation chip each → upload a renamed-columns pack via slide-over → confirm mapping → run → watch stepper progress → (with `STRATEGYOS_REQUIRE_HUMAN_REVIEW=true`) approve from the chat → run completes → KPI cards update.

## 8. Out of scope (do not build)

- LLM/conversational layer, multi-turn memory, websockets/SSE (polling is fine), React/Vue/build toolchain, dark mode, mobile layout, redesign of the artifact-inspector/vector-search consoles (they just move), any change to detectors/workflow/auth.

## 9. Suggested commit sequence

1. `Extract dashboard shell from api.py into static assets (no behavior change)` — Phase 1, tests green unmodified.
2. `Add chat+dashboard shell with KPI strip and deterministic Q&A thread` — Phase 2 layout + chat + cards, shell tests updated in the same commit.
3. `Move intake flow to slide-over and review actions into chat thread` — remaining Phase 2 + manual acceptance.
