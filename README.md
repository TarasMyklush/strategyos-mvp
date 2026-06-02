# StrategyOS MVP

Production-shaped MVP scaffold for the StrategyOS finance-agent POC.

## What This Implements

- Sanitized `agent_input` preparation.
- Human-only evaluation answer-key separation.
- Source hash manifest.
- Structured ingestion for AP, AR, GL, trial balance, master data, POs, and treasury workbook.
- PDF/text evidence extraction with citation IDs.
- Deterministic finance skills for planted leakage classes.
- Finance Analyst and Finance Auditor agents.
- Knowledge Graph Builder agent with a local strong-node graph export.
- LangGraph-compatible workflow adapter with a local fallback when LangGraph is not installed.
- Case file, working-capital memo, Q&A transcript, knowledge graph, and ping-pong audit log generation.

## Run

From the implementation folder:

```bash
cd "/Users/taras/Desktop/Taras/sp soft/Enterprise OS/strategyos_mvp"
/Users/taras/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m strategyos_mvp.run_poc
```

Outputs are written to:

```text
outputs/StrategyOS MVP Run/
```

## Production Notes

The local fallback workflow is deliberately deterministic. For production, install LangGraph and wire the same nodes through the LangGraph adapter with a durable checkpointer and human approval interrupt.
