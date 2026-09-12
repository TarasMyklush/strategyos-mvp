"""Human-readable presentation of a fact already authorized by claim_api."""
from html import escape
import json

from fastapi.responses import HTMLResponse

from .fact_rendering import fact_registry


def fact_page(result):
    record = result['record']
    registry = fact_registry([record])
    fact = next(iter(registry.values()), None)
    text = fact['display_text'] if fact else str(record.get('label') or 'Business record')
    provenance = escape(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    content = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Business fact · Kyvern</title><style>
body{{margin:0;background:#fbf8f2;color:#192c35;font:18px/1.6 system-ui,sans-serif}}
main{{max-width:850px;margin:5vh auto;padding:24px}}h1{{font-family:Georgia,serif}}
.fact,pre{{white-space:pre-wrap;overflow-wrap:anywhere}}details{{margin-top:2em}}
pre{{font-size:13px}}summary{{cursor:pointer}}a{{color:inherit}}
</style></head><body><main><p>Kyvern · Evidence</p><h1>Business fact</h1>
<p class="fact" dir="auto">{escape(text)}</p>
<p>This record was checked against your current access permissions when this page opened.</p>
<p>Analysis as of: {escape(str(result.get('analysis_as_of') or 'Not recorded'))}</p>
<details><summary>Technical details and source lineage</summary><pre>{provenance}</pre></details>
</main></body></html>'''
    return HTMLResponse(content, headers={
        'Cache-Control': 'private, no-store',
        'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'",
        'X-Content-Type-Options': 'nosniff',
    })
