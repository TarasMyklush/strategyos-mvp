# CEO view blocks explained

Date: 2026-07-12

This note explains the main blocks in the StrategyOS CEO view and what they actually do in the current implementation.

## Implementation model

The CEO view is a single-page executive workspace, not a set of independent pages. On load, the frontend:

1. calls `/ui/session`;
2. calls the latest-run endpoint selected for that session;
3. stores the returned packet in `state.latestPacket`;
4. renders the page from that packet plus local UI state.

The relevant frontend entrypoint is `strategyos_mvp/static/executive.js`, especially `refresh()` and `renderPersonaView()`.

The main packet sections used by the CEO view are:

- `executive_diagnostics`
- `plan_health`
- `publication`
- `board_portal`
- `drilldown`
- `agent_modules`
- `assistant_public_context`
- `chat`

Most user actions either:

- change frontend state and re-render part of the page;
- switch the active view/tab;
- open Hermes with contextual prompt data;
- show local UI feedback such as a toast.

## 1. Top bar, persona, and tabs

The top bar controls the active view and active persona.

Visible controls:

- `Diagnostics`
- `Assistants`
- `Knowledge`
- persona dropdown, e.g. `Group CEO`
- avatar/profile control

What it does:

- switches `state.activeView`;
- switches `state.activePersona`;
- resets selected driver/thread state when persona changes;
- opens profile/settings;
- toggles theme;
- re-renders the page.

What it does not do:

- it does not create a new backend run;
- it does not mutate the governed packet;
- it does not deploy or start agents.

## 2. Hero card

The hero card is the CEO headline.

It displays:

- greeting;
- executive summary;
- score/ring;
- board state;
- report count;
- active agent count;
- items needing review;
- suggested Hermes prompt chips.

Data sources:

- `executive_diagnostics.hero`
- `plan_health`
- `publication`
- `board_portal`
- `agent_modules`

What it does:

- renders the executive posture from the latest governed packet;
- computes and draws the circular score ring client-side;
- renders mini stats from board, report, agent, and review data;
- sends prompt-chip clicks to Hermes through `askAssistant()`.

CEO meaning:

This block answers: “Where do we stand right now, and is the board packet ready enough to discuss?”

## 3. The group index / KPI driver tiles

The KPI driver tiles are the circular cards under “The group index.”

Examples include:

- recoverable value;
- governed cases;
- citation resolution;
- challenged cases.

Data source:

- visible drivers from the persona blueprint / `executive_diagnostics.driver_grid`;
- related details from `drilldown`.

What it does:

- renders the current governed measures;
- marks one driver as active;
- on click, sets `state.activeDriverKey`;
- updates the URL/history;
- re-renders the driver grid, drill-down panel, and summary;
- scrolls the drill-down panel into view.

CEO meaning:

This is the main business lens selector. The tile is not only a metric; it controls the rest of the dashboard context.

## 4. “What’s driving it”

This is the detail panel for the selected KPI driver.

It can show:

- driver story;
- trend vs plan;
- lifting factors;
- dragging factors;
- evidence-linked explanation;
- driver-specific Hermes composer.

Data source:

- active driver;
- `drilldown`;
- `board_portal`;
- `publication`.

What it does:

- changes when a KPI tile is selected;
- explains why the selected metric is moving;
- passes active driver context into Hermes when the user asks a question from this area.

CEO meaning:

This block translates a metric into a decision story: what changed, what caused it, and what to ask next.

## 5. “What matters now”

This lower rail contains three major cards:

- `Findings & concerns`
- `Developments since you were here`
- `Week ahead`

Data sources:

- persona blueprint findings/developments/week;
- `drilldown.lower_rail`;
- reconciliation from `assistant_public_context.findings_reconciliation`.

What it does:

- expands/collapses finding and development rows;
- shows detail text inline;
- opens Hermes with contextual prompts such as “Ask why this matters” or “Project impact on plan”;
- lets the user select a week-ahead event;
- sends event-specific questions to Hermes;
- for “Request missing data,” passes hidden structured context including event title, timing, board state, active driver, and prep notes.

CEO meaning:

This block answers: “What needs my attention before the next board or operating decision?”

## 6. Findings reconciliation

This appears under `Findings & concerns` when the visible findings do not represent the whole recoverable value total.

It shows:

- top displayed cases;
- remaining governed cases;
- total recoverable value.

Data source:

- `assistant_public_context.findings_reconciliation`.

What it does:

- reconciles the headline number with the subset of itemized evidence shown in the UI;
- prevents the top-line recoverable value from looking unsupported when only the top findings are displayed.

CEO meaning:

This explains the difference between “visible examples” and “total governed value.”

## 7. Explore scenarios / Leaders’ Corner

This area combines scenario prompts and executive content.

It displays:

- scenario prompt buttons;
- Leaders’ Corner video card;
- topic-specific Hermes actions;
- video/player links.

Data source:

- `drilldown.gravity`;
- persona/content configuration.

What it does:

- scenario buttons send structured prompts to Hermes;
- video/topic actions can open Hermes with a topic prompt;
- video/player controls remain UI/media actions.

CEO meaning:

This is a decision-support and learning block. It lets the CEO explore implications without leaving the governed dashboard.

## 8. Agents section in Diagnostics

This section shows agent activity directly inside the Diagnostics view.

It includes:

- activity summary;
- running agents/modules;
- audit logs;
- approval-held agents;
- discoverable agents;
- search;
- browse action.

Data sources:

- `agent_modules`;
- `assistant_public_context.agent_activity`;
- `assistant_public_context.running_agents`;
- connector catalogue where applicable.

What it does:

- expands and collapses running-agent rows;
- opens audit log detail;
- records local approval state for approval-held rows;
- filters discoverable agents by search text;
- “Browse all agents” switches to the Assistants tab and opens the catalogue section.

What it does not do:

- it does not truly deploy a new autonomous agent from the CEO screen;
- approval state shown in this panel is session/UI state unless backed by a dedicated workflow route;
- rows represent governed module telemetry and available routes, not free-running invisible bots.

CEO meaning:

This block answers: “What is working on my packet right now, what is blocked, and what can be added or inspected?”

## 9. Assistants tab / Governed Assistant Network

The Assistants tab gives the fuller module-network view.

It displays:

- module count;
- running/pending/blocked filters;
- module list;
- optional agent catalogue.

Data source:

- `agent_modules.running`;
- `agent_modules.discoverable`;
- status-derived ranks.

What it does:

- filter dropdown changes `state.networkStatusFilter`;
- filter chips show running/pending/blocked subsets;
- clicking a module row opens Hermes with a contextual question about that module;
- catalogue visibility is controlled by `state.assistantCatalogueOpen`.

CEO meaning:

This is a governed module status board. It shows what is running, what is waiting, and what needs attention.

## 10. Knowledge tab / Knowledge graph

The Knowledge tab renders the graph universe.

It displays:

- primary nodes from board context;
- derived evidence/source/relationship nodes;
- edges;
- question lenses;
- density toggle;
- zoom controls;
- fit/reset;
- focus mode;
- node inspector.

Data source:

- `assistant_public_context.kg_nodes`;
- `assistant_public_context.kg_edges`.

What it does:

- builds a visual graph from governed packet nodes and edges;
- adds synthetic visual nodes for evidence density and relationship paths;
- supports pan, zoom, keyboard navigation, dense/compact mode, and focus mode;
- opens an inspector when a node is clicked;
- can ask Hermes about the selected graph node.

Important distinction:

Synthetic graph nodes are visual context. They are not new business claims.

CEO meaning:

This block answers: “How do the board signals, findings, evidence, and documents relate to each other?”

## 11. Board portal / Reports

This area appears in the Knowledge/board surface.

It displays:

- board lifecycle state;
- board KPIs;
- deck release status;
- frozen snapshot;
- lifecycle actions;
- meeting posture;
- report artifacts.

Data sources:

- `board_portal`;
- `publication`;
- `executive_modes`.

What it does:

- lifecycle tabs change `state.activeBoard`;
- report/board copy changes by lifecycle state;
- board action chips open Hermes with board-context prompts;
- snapshot cards show local operator-surface availability feedback;
- report artifact list is rendered from `publication.available_artifacts`.

CEO meaning:

This block answers: “What can safely go to the board, where are we in the lifecycle, and what remains before/after the meeting?”

## 12. Ask Hermes drawer

The Hermes drawer is the assistant panel.

It opens from:

- the bottom `Ask Hermes` launcher;
- hero prompts;
- driver prompts;
- lower-rail prompts;
- board action chips;
- knowledge graph inspector;
- assistant/module rows.

What it does:

- stores local conversation threads;
- filters stale/system/bug/error threads out of CEO view;
- sends questions to `/assistant/chat`;
- includes persona, board state, entrypoint, active driver context, and hidden event context where relevant;
- renders answers and metadata;
- shows retry controls for failed assistant calls.

CEO meaning:

Hermes is the explanation/action layer over the dashboard. It should answer from the current governed board packet, not invent outside narrative.

## 13. Hermes ↔ assistants floating panel

This is the smaller assistant-network exchange panel.

It displays:

- module exchanges;
- module status;
- short message snippets;
- follow-up/feedback controls.

Data source:

- running modules derived from `agent_modules`;
- approval items if no running module feed exists.

What it does:

- toggles a live-looking exchange panel;
- shows derived handoff/status messages;
- does not currently represent independent live multi-agent chat over a message bus.

CEO meaning:

This gives an executive-readable view of the assistant network’s current handoffs.

## End-to-end mental model

The CEO view is a board-readiness cockpit:

- hero = current posture;
- KPI tiles = business lens selector;
- driver drilldown = explanation of the selected metric;
- lower rail = what needs attention;
- agents = governed runtime visibility;
- assistants tab = fuller module status and catalogue;
- knowledge graph = evidence relationships;
- board portal = board-safe lifecycle and reports;
- Hermes = contextual explanation and next-action interface.

