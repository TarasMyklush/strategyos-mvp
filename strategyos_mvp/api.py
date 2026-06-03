from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    from pydantic import BaseModel
except Exception as exc:  # pragma: no cover - optional cloud dependency
    raise RuntimeError("FastAPI and pydantic are required to run the StrategyOS API.") from exc

from .config import CONFIG
from .prepare_inputs import prepare_agent_input
from .run_poc import run_strategyos_workflow
from .storage import object_store_status


class RunRequest(BaseModel):
    dataset: str | None = None
    run_dir: str | None = None
    skip_prepare: bool = False
    sync_artifacts: bool | None = None


app = FastAPI(title="StrategyOS MVP API", version="0.1.0")


def _latest_summary() -> dict[str, Any] | None:
    summary_path = CONFIG.default_run_dir / "run_summary.json"
    if not summary_path.exists():
        return None
    return json.loads(summary_path.read_text(encoding="utf-8"))


def _status_label(value: bool) -> str:
    return "Configured" if value else "Missing"


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    latest = _latest_summary()
    latest_html = (
        """
        <section class="panel empty">
          <h2>No Run Yet</h2>
          <p>No workflow run has been persisted in the default output folder.</p>
        </section>
        """
        if latest is None
        else f"""
        <section class="panel">
          <div class="panel-title">
            <h2>Latest Run</h2>
            <a href="/runs/latest">JSON</a>
          </div>
          <dl class="metrics">
            <div><dt>Findings</dt><dd>{html.escape(str(latest.get("findings", "n/a")))}</dd></div>
            <div><dt>Locked</dt><dd>{html.escape(str(latest.get("locked_findings", "n/a")))}</dd></div>
            <div><dt>Recoverable SAR</dt><dd>{float(latest.get("total_recoverable_sar", 0)):,.2f}</dd></div>
            <div><dt>State</dt><dd>{html.escape(str(latest.get("state_store", {}).get("status", "n/a")))}</dd></div>
          </dl>
          <p class="path">Run folder: {html.escape(str(latest.get("run_dir", "n/a")))}</p>
        </section>
        """
    )
    services = [
        ("Postgres", bool(CONFIG.database_url)),
        ("Redis", bool(CONFIG.redis_url)),
        ("Neo4j", bool(CONFIG.neo4j_uri)),
        ("Object Store", object_store_status().get("enabled", False)),
    ]
    service_rows = "\n".join(
        f"""
        <div class="service">
          <span>{html.escape(name)}</span>
          <strong class="{'ok' if enabled else 'warn'}">{_status_label(enabled)}</strong>
        </div>
        """
        for name, enabled in services
    )
    return f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>StrategyOS Local Status</title>
        <style>
          :root {{
            color-scheme: light;
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #f6f7f9;
            color: #1d232a;
          }}
          * {{ box-sizing: border-box; }}
          body {{ margin: 0; min-height: 100vh; }}
          main {{ max-width: 1040px; margin: 0 auto; padding: 36px 24px 48px; }}
          header {{ display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; margin-bottom: 24px; }}
          h1 {{ font-size: 28px; line-height: 1.15; margin: 0 0 8px; font-weight: 720; }}
          h2 {{ font-size: 17px; margin: 0; }}
          p {{ color: #4f5b68; margin: 0; line-height: 1.5; }}
          a {{ color: #1559b7; text-decoration: none; font-weight: 650; }}
          a:hover {{ text-decoration: underline; }}
          .badge {{ border: 1px solid #b7dcc3; background: #e7f6ec; color: #176335; border-radius: 999px; padding: 7px 11px; font-size: 13px; font-weight: 700; white-space: nowrap; }}
          .grid {{ display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.8fr); gap: 16px; }}
          .panel {{ background: #ffffff; border: 1px solid #dfe4ea; border-radius: 8px; padding: 18px; box-shadow: 0 1px 2px rgba(29, 35, 42, 0.04); }}
          .panel-title {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 14px; }}
          .metrics {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 0 0 14px; }}
          .metrics div {{ border: 1px solid #edf0f3; background: #fafbfc; border-radius: 6px; padding: 12px; min-width: 0; }}
          dt {{ color: #647181; font-size: 12px; margin-bottom: 6px; }}
          dd {{ margin: 0; font-size: 20px; font-weight: 760; overflow-wrap: anywhere; }}
          .path {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; background: #f6f7f9; border-radius: 6px; padding: 10px; overflow-wrap: anywhere; }}
          .services {{ display: grid; gap: 10px; margin-top: 14px; }}
          .service {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #edf0f3; padding: 10px 0; gap: 16px; }}
          .service:last-child {{ border-bottom: 0; }}
          .ok {{ color: #176335; }}
          .warn {{ color: #9a3412; }}
          .links {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 14px; }}
          .links a {{ border: 1px solid #d8dee6; border-radius: 6px; padding: 8px 10px; background: #fff; }}
          .empty {{ min-height: 190px; display: grid; align-content: center; gap: 8px; }}
          @media (max-width: 760px) {{
            main {{ padding: 24px 16px 36px; }}
            header {{ display: block; }}
            .badge {{ display: inline-block; margin-top: 14px; }}
            .grid, .metrics {{ grid-template-columns: 1fr; }}
          }}
        </style>
      </head>
      <body>
        <main>
          <header>
            <div>
              <h1>StrategyOS Local Status</h1>
              <p>Human-readable test page for the local Docker deployment.</p>
            </div>
            <span class="badge">API Online</span>
          </header>
          <div class="grid">
            {latest_html}
            <section class="panel">
              <div class="panel-title">
                <h2>Services</h2>
                <a href="/health">Health JSON</a>
              </div>
              <div class="services">{service_rows}</div>
              <div class="links">
                <a href="/runs/latest">Latest Run JSON</a>
                <a href="/docs">API Docs</a>
              </div>
            </section>
          </div>
        </main>
      </body>
    </html>
    """


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "workspace_root": str(CONFIG.workspace_root),
        "output_root": str(CONFIG.output_root),
        "object_store": object_store_status(),
        "database_configured": bool(CONFIG.database_url),
        "redis_configured": bool(CONFIG.redis_url),
        "neo4j_configured": bool(CONFIG.neo4j_uri),
    }


@app.post("/runs")
def create_run(request: RunRequest) -> dict[str, Any]:
    dataset = Path(request.dataset).expanduser().resolve() if request.dataset else None
    run_dir = Path(request.run_dir).expanduser().resolve() if request.run_dir else CONFIG.default_run_dir
    summary = run_strategyos_workflow(
        dataset=dataset,
        run_dir=run_dir,
        skip_prepare=request.skip_prepare,
        sync_artifacts=request.sync_artifacts,
    )
    return summary


@app.get("/runs/latest")
def latest_run() -> dict[str, Any]:
    summary = _latest_summary()
    if summary is None:
        return {"status": "missing", "run_dir": str(CONFIG.default_run_dir)}
    return summary


@app.post("/inputs/prepare")
def prepare_inputs() -> dict[str, str]:
    agent_input, evaluation = prepare_agent_input()
    return {"agent_input": str(agent_input), "evaluation": str(evaluation)}
