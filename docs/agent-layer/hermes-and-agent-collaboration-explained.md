# Hermes and agent collaboration explained

Date: 2026-07-12

This note explains what “Hermes” means in StrategyOS and how agent collaboration works inside the current app implementation.

## Short answer

Hermes is the CEO-facing assistant identity for the StrategyOS executive surface.

It is not a separate autonomous agent process running by itself in the browser. In the current implementation, Hermes is:

- a persona-specific assistant name shown in the UI;
- a chat drawer and thread experience in the frontend;
- a request path to `/assistant/chat`;
- a server-side assistant orchestration layer that answers from the current governed packet, findings, board context, graph context, and driver context;
- a routing and explanation layer over governed modules, not an unrestricted chatbot.

The “agent collaboration” visible in the CEO app is currently a governed module/handoff surface. It shows modules, statuses, audit trails, approval dependencies, and derived handoff messages. It is not yet a fully independent multi-agent runtime with each UI card backed by a separate long-running agent conversation.

## Where Hermes appears

Hermes appears in several places:

- bottom `Ask Hermes` launcher;
- assistant drawer;
- hero prompt chips;
- driver-specific prompt actions;
- lower-rail actions such as “Ask why this matters” and “Request missing data”;
- board action chips;
- knowledge graph inspector;
- assistant/module row clicks.

In code, the main frontend path is:

- `strategyos_mvp/static/executive.html`
  - `#chat-launcher`
  - `#assistant-drawer`
  - `#assistant-form`
  - `#assistant-input`
- `strategyos_mvp/static/executive.js`
  - `renderAssistantStudio()`
  - `askAssistant()`
  - `buildAssistantReply()`

## What happens when a user asks Hermes a question

The frontend flow is:

1. The user clicks a prompt, action chip, module row, graph node action, or types into the assistant input.
2. The UI calls `askAssistant(prompt, sourceElement, hiddenContext?)`.
3. The UI creates or selects a local thread.
4. The user message is pushed into local thread state.
5. A pending assistant message appears: “Checking the board data…”
6. The UI calls `buildAssistantReply()`.
7. `buildAssistantReply()` sends a POST request to `/assistant/chat`.
8. The backend returns a structured assistant response.
9. The pending message is replaced with the final answer and metadata.

The request body can include:

- `question`
- `mode`
- `persona`
- `trace_id`
- `assistant_context`
- `driver_context`
- `source`
- `entrypoint`
- `run_id`, when a concrete run id is available and safe to send

The UI deliberately avoids sending `run_id = "latest-public"` as a UUID-like id.

## What context Hermes receives

Hermes is not answering from only the typed question. The app attaches context based on where the question came from.

Examples:

### Generic Ask Hermes launcher

Sends:

- persona;
- current board state;
- general assistant entrypoint.

### KPI / driver area

Sends:

- active driver key;
- driver label;
- metric/value;
- status;
- detail/story;
- movers/lifters/draggers.

Purpose:

Hermes can answer “why did this metric move?” using the selected KPI context.

### Board portal

Sends:

- board lifecycle state;
- board portal entrypoint;
- board action key.

Purpose:

Hermes answers in terms of board-safe lifecycle and report posture, not stale revenue/driver context.

### Week ahead / missing data

Sends hidden structured context:

- event title;
- event timing;
- board state;
- active driver label;
- active driver metric;
- prep notes;
- guidance to identify dashboard-backed gaps.

Purpose:

Hermes should answer the actual missing-data question instead of generic advice.

### Knowledge graph

Sends:

- selected node context;
- graph/board evidence prompt.

Purpose:

Hermes can explain a node using the governed graph context.

### Assistant/module row

Sends:

- module name;
- lane/owner;
- status;
- prompt asking what the module is doing, whether it is blocked, and what it needs.

Purpose:

Hermes explains module status in executive terms.

## Backend assistant path

The backend endpoint is:

- `POST /assistant/chat`

Relevant backend code:

- `AssistantChatRequest`
- `_assistant_chat_response()`
- `assistant_chat()`
- `get_orchestrator()`
- `AssistantOrchestrator`

The backend resolves a public-safe or authenticated assistant context, then routes the question through deterministic and/or LLM-backed orchestration depending on mode and availability.

The important implementation point:

Hermes is the named user-facing assistant, while the backend orchestration engine is the actual answer-generation mechanism.

## What the server seeds for Hermes

The server sends a `chat` contract in the latest-run payload.

That contract includes:

- assistant identity;
- persona id;
- persona label;
- active board state;
- starter threads;
- starter prompts;
- route contracts;
- notes about thread storage.

Current storage model:

- frontend owns per-run thread history;
- thread persistence is client/session-oriented;
- server seeds identity, starter threads, and workflow posture;
- server does not currently own durable chat memory for every drawer thread.

This matters because a refreshed browser session may not behave like a full enterprise chat history product unless server-side memory is added.

## What “agents” mean in the CEO app

The CEO app uses “agents” in three related but different ways.

### 1. Governed modules

These are the core module rows shown in the assistant network.

Current modules include:

- Cash recovery watch
- Evidence closure monitor
- Board-pack compiler
- Runtime guardrail

They are assembled by `_agent_modules_payload()`.

Each module has:

- `module_id`
- `label`
- `status`
- `lane`
- `summary`
- `route`
- `output_metric`
- `approval_dependency`

These modules are derived from the current run, findings, publication state, audit summary, runtime config, and workflow state.

### 2. Discoverable agents

These are available routes/capabilities the UI can show in discovery/catalogue sections.

Examples:

- CEO brief
- Board room memory
- Reviewer gate console
- Operator resume relay
- System health monitor
- connector-backed marketplace items

They are also assembled into the app payload. Some depend on the principal role.

In the current CEO view, these are discoverable surfaces and governed routes, not one-click deployment of arbitrary new background bots.

### 3. Assistant-to-assistant handoff display

The floating `Hermes ↔ assistants` panel shows a derived collaboration view.

It is built from:

- running modules, if available;
- approval gates, as fallback.

Each exchange includes:

- id;
- assistant/module name;
- unit/lane;
- status;
- topic;
- short messages.

The backend chat contract marks this as:

- `a2a.enabled = true`
- `a2a.mode = "derived_handoff_only"`

That phrase is important. It means the UI displays handoffs derived from governed workflow/module data. It does not currently mean there is a live multi-agent message bus where separate autonomous assistants negotiate in real time.

## How collaboration actually works today

Current collaboration model:

1. The backend builds the latest governed packet.
2. The packet includes publication state, findings, board portal state, audit status, strategy graph context, and agent module summaries.
3. The frontend renders modules and assistant handoffs from that packet.
4. User actions open Hermes with context.
5. Hermes sends the contextual question to `/assistant/chat`.
6. The backend orchestrator answers using resolved context.
7. The UI shows the answer in the Hermes drawer.

In practical terms:

- agents collaborate through shared packet state and explicit handoff/status surfaces;
- Hermes acts as the explanation and routing interface over those surfaces;
- approvals and workflow dependencies are shown to the CEO as gated states;
- actual durable execution remains bounded to governed backend routes, not hidden browser automation.

## What is real versus presentational

Real:

- latest governed run data;
- findings and recoverable value;
- citation/challenge counts;
- publication/report state;
- board lifecycle state;
- module statuses derived from run/workflow state;
- connector catalogue visibility;
- `/assistant/chat` assistant response path;
- graph context derived from public-safe assistant packet.

Partly presentational/client-side:

- local assistant thread history;
- expanded/collapsed rows;
- selected driver;
- selected board lifecycle tab;
- approval visual state in some CEO-side agent rows;
- synthetic graph density nodes;
- floating A2A exchange display.

Not currently implemented as full autonomous collaboration:

- each named assistant running as a separate process;
- live inter-agent negotiation visible in real time;
- server-owned durable chat memory for every Hermes thread;
- CEO-side one-click deployment of arbitrary agents;
- independent agent task queues launched directly from the CEO card UI.

## Recommended product language

Use:

- “Hermes is the CEO-facing assistant over the governed board packet.”
- “Assistant network modules show governed status, evidence, and handoff context.”
- “Hermes answers with the current board, finding, driver, and graph context.”
- “Agent collaboration is represented through governed module states and derived handoffs.”

Avoid, unless the backend is expanded:

- “Hermes is autonomously running the company.”
- “Agents are live-chatting with each other in real time.”
- “Clicking deploy starts a new independent agent worker.”
- “The CEO chat has durable enterprise memory.”

## Desired future architecture, if we want real multi-agent collaboration

To make the visible collaboration fully real, the system would need:

1. durable server-side conversation memory;
2. an agent task table or queue;
3. persisted handoff events;
4. explicit agent identities and capabilities;
5. execution workers per agent/module;
6. audit log entries for every agent action;
7. approval gates enforced server-side;
8. WebSocket or polling channel for live status updates;
9. a distinction between “assistant explanation” and “agent execution” in the API contract.

Until then, the current app should be described as a governed executive cockpit with assistant-guided module visibility, not a fully autonomous multi-agent operating system.

The implementation-ready target design is documented in [StrategyOS agents layer — implementation-ready design](agents-layer-design.md).
