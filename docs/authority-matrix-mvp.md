# StrategyOS Authority Matrix — Implemented Contract

## Purpose

The Authority Matrix is the published governance contract that determines what each persona, AI assistant and specialist agent may see and do. It mirrors the organisation's real delegation-of-authority model and gives every refusal an understandable policy reason.

## Policy model

Each policy cell is:

`subject × domain × right`

- Subject types: `persona`, `assistant`, `agent`
- Initial domains: `finance`, `hr`, `contracts`, `board_materials`, `assistant_team`
- Rights: `none`, `view`, `analyse`, `recommend`, `act-with-approval`
- Action classes may have an approver chain, for example `Legal → Group CFO → Group CEO`.

The order of rights is monotonic: a higher right includes the lower information rights, but `act-with-approval` never implies autonomous execution.

## Enforcement contract

Every protected read, answer, recommendation and action request must resolve an effective authority decision before data is returned or work is started.

An authority decision contains:

- requesting subject;
- requested domain and action class;
- required right;
- resolved right;
- policy version and matrix row;
- allow/deny result;
- approver chain when approval is required.

A denial must be user-readable, for example:

> Iris cannot view board materials — Authority Matrix §3, assistant:Iris × board_materials.

The public matrix page may expose the policy structure and rights, but not private operational data protected by those rights.

## Delivered behavior

- Authority Matrix navigation and readable grid.
- CEO/CIO-authorized editing in the executive UI and API.
- Persona, assistant and agent subjects.
- Five initial information domains and five rights.
- Visible approver chains.
- The AI Assistant team-readiness confidentiality rule reads the matrix instead of a hardcoded persona check.
- Tenant-scoped versioned persistence in PostgreSQL, with an atomic JSON fallback for local deployments.
- Optimistic version checks prevent one editor from silently overwriting another.
- Every published change records the actor, timestamp, version and complete policy snapshot in an audit log.
- Assistant requests are classified by information domain and required right before retrieval or answer generation.
- Agent evidence reads and consequential tool calls are checked before the tool handler executes.
- Denials return a structured refusal with the exact policy version and matrix-row citation.
- Consequential agent tools continue through the existing verified capability-token and approval path after the matrix permits them.
- Direct API regression tests prove denied assistant and agent calls cannot bypass the browser policy.

## Enforcement sequence

For each governed request, StrategyOS now:

1. Resolves the tenant and published matrix version.
2. Maps the persona, assistant or installed agent to its matrix subject.
3. Classifies the requested domain and minimum right.
4. Denies before retrieval or tool execution when the matrix is insufficient.
5. Returns the policy row and version in the refusal.
6. For an allowed consequential agent action, applies the existing effective-authority intersection and verifies its scoped capability token before dispatch.

The browser is therefore a policy editor and explanation surface; enforcement remains server-side even when the API is called directly.

## Deliberate scope boundary

This contract is complete for the R3 StrategyOS product scope. Client-specific IAM/IGA synchronization and migration of a client's existing delegation-of-authority records remain deployment integrations, not missing product enforcement.
