"""Rebuild source-derived projections before review; approved runs are immutable here."""
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from strategyos_mvp.config import CONFIG
from strategyos_mvp import state_store
from strategyos_mvp.source_finance_kpis import derive_source_finance_kpis
from strategyos_mvp.source_strategy_enrichment import derive_strategy_enrichment


def rebuild(run_id, reason):
    connection, failure = state_store.database_connection()
    if failure or connection is None:
        raise RuntimeError('The durable run store is required.')
    with connection as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT summary_json,approved_at FROM strategyos_runs WHERE id=%s FOR UPDATE', (run_id,))
            row = cur.fetchone()
            if row is None:
                raise ValueError('Run not found.')
            summary, approved_at = row
            if approved_at is not None or summary.get('approval_status') == 'approved' or summary.get('status') == 'completed':
                raise ValueError('Create a new run to change an approved projection.')
            if (summary.get('tenant_context') or {}).get('tenant_id') != CONFIG.tenant_slug:
                raise ValueError('Run belongs to another tenant.')
            root = Path(summary['dataset']).resolve()
            manifest = json.loads((root/'release-source-manifest.json').read_text())
            for entry in manifest['files']:
                source = (root/entry['pack_path']).resolve()
                if not source.is_relative_to(root) or hashlib.sha256(source.read_bytes()).hexdigest() != entry['sha256']:
                    raise ValueError('Release source manifest verification failed.')
            directory = Path(summary['run_dir']).resolve()
            if not directory.is_relative_to(CONFIG.output_root.resolve()):
                raise ValueError('Run output is outside this deployment.')
            before = summary.get('finance_kpi')
            summary['finance_kpi'] = derive_source_finance_kpis(root)
            summary['strategy_enrichment'] = derive_strategy_enrichment(root, finance_kpi=summary['finance_kpi'])
            summary['projection_rebuild'] = {
                'reason':reason, 'revision':os.environ.get('STRATEGYOS_RELEASE_SHA'),
                'at':datetime.now(timezone.utc).isoformat(), 'source_digest':manifest['digest'],
                'previous_finance_sha256':hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest(),
                'finance_sha256':hashlib.sha256(json.dumps(summary['finance_kpi'],sort_keys=True).encode()).hexdigest(),
                'approval_status':'pending',
            }
            encoded = json.dumps(summary,indent=2)
            cur.execute('UPDATE strategyos_runs SET summary_json=%s::jsonb WHERE id=%s', (encoded,run_id))
        conn.commit()
    temporary = directory/'run_summary.rebuilding'
    temporary.write_text(encoded)
    os.replace(temporary,directory/'run_summary.json')
    return {'run_id':run_id,'projection_rebuild':summary['projection_rebuild'],'components':summary['finance_kpi']['components']}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',required=True);parser.add_argument('--reason',required=True)
    args=parser.parse_args()
    print(json.dumps(rebuild(args.run_id,args.reason),indent=2))
