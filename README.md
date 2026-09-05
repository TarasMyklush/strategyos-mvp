# StrategyOS

StrategyOS provides governed finance analysis, executive diagnostics, contextual question answering and a specialist agent runtime. This repository on `main` is the canonical implementation. It includes the enriched synthetic demonstration dataset and portable regression fixtures.

The broader enterprise System of Intent is still under development. Requirements, implementation and readiness are separated explicitly:

| Read this | Purpose |
|---|---|
| [Requirements](docs/requirements.md) | Single active product specification, financial formulas and acceptance criteria |
| [Architecture](docs/architecture.md) | Current implementation boundaries and extension rules |
| [Gap analysis](docs/assessment/gap-analysis.md) | Evidence-backed gaps and remaining work |
| [Validation](docs/assessment/validation.md) | Latest consolidation checks and their limits |
| [Operations](docs/operations.md) | Local setup, isolated tests, release and cleanup rules |
| [Deployment](deploy/README.md) | Compose, identity, provider policy and deployment commands |
| [Data](data/README.md) | Current demo inputs versus fixed regression fixtures |
| [Consolidation receipt](docs/maintenance/consolidation.md) | What moved, what was removed and recovery information |

## Quick start

Python 3.11+ is required; CI uses 3.12. Run from this directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e . pytest
make test
.venv/bin/python -m uvicorn strategyos_mvp.api:app --host 127.0.0.1 --port 8000
```

Use the deployment runbook for authenticated hosted operation. Local OCR requires platform tools; service integration tests require dedicated services. The default demo dataset is `data/demo/01_Synthetic_Dataset`. Hosted paths and provider access are explicitly configured through environment variables.

## Maintaining one source of truth

Update requirements, affected code/tests and the gap record together. Do not add dated duplicate implementation plans or alternate “canonical” documents. `docs/assessment/gap-register.json` is the gap source; regenerate its readable view with `python scripts/render_gap_analysis.py`. Test outputs and runtime state stay outside tracked source. Never commit credentials.

The consolidation brought local main forward from `9fa5316` to reviewed baseline `c03e958` before applying cleanup. A local consolidation does not prove GitHub main, deployed images or selected live run data are synchronized; see the release gaps.
