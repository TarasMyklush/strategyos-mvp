"""Release identity, actual source history and tenant inference health."""
import json
import os
from pathlib import Path
from typing import Any
from fastapi import APIRouter, HTTPException
from .auth import require_role
from . import state_store
from .config import CONFIG
from .access_scope import guard_summary

router=APIRouter()


@router.get('/api/deployment')
def deployment(principal: dict[str,Any]=require_role('executive','operator','reviewer','bu')):
    from .run_registry import load_latest_run_summary
    summary=load_latest_run_summary() or {}
    guard_summary(summary)
    root=Path(str(summary.get('dataset') or summary.get('dataset_root') or ''))
    source=root/'release-source-manifest.json'
    source_manifest=json.loads(source.read_text()) if source.is_file() and summary else {}
    path=CONFIG.workspace_root/'.strategyos_mvp_data/releases/current.json'
    manifest=json.loads(path.read_text()) if path.is_file() else {}
    revision=os.getenv('STRATEGYOS_RELEASE_SHA','unrecorded')
    application_matches=bool(manifest and revision!='unrecorded' and manifest.get('application_revision')==revision)
    return {'environment':CONFIG.environment_label,'application_revision':revision,
      'manifest_application_matches':application_matches,
      'image_digest':manifest.get('image_digest') if application_matches else None,
      'schema_sha256':manifest.get('schema_sha256') if application_matches else None,
      'selected_run_id':summary.get('run_id'),'manifest_run_matches':bool(manifest and manifest.get('run_id')==summary.get('run_id')),
      'source_digest':source_manifest.get('digest'),'source_classification':source_manifest.get('classification','not_declared'),
      'source_period':source_manifest.get('period'),'source_search':summary.get('source_search',{'status':'not_indexed'}),'data_region':os.getenv('STRATEGYOS_DATA_REGION','Not attested'),
      'model_provider':CONFIG.llm_provider if CONFIG.model_provider_enabled else 'disabled','model':CONFIG.llm_model if CONFIG.model_provider_enabled else None,
      'model_processing':os.getenv('STRATEGYOS_MODEL_PROCESSING_REGION','External provider; residency not attested') if CONFIG.model_provider_enabled else 'No model calls enabled',
      'run_policy':CONFIG.run_policy.mode,'approved_external_modes':list(CONFIG.run_policy.approved_external_modes),
      'external_business_connections':'deferred','fallback_provider':'none'}


@router.get('/api/plan/history')
def history(principal: dict[str,Any]=require_role('executive','bu')):
    runs=state_store.list_recent_runs(limit=100)
    if isinstance(runs,dict):raise HTTPException(503,'Plan history requires the durable database.')
    points=[]
    for run in reversed(runs):
        summary=run.get('summary_json') or {}
        guard_summary(summary)
        health=(summary.get('strategy_enrichment') or {}).get('plan_health') or {}
        if not health.get('commitments'):continue
        points.append({'run_id':run['run_id'],'recorded_at':run.get('created_at'),
          'approval_status':summary.get('approval_status'),'score':health.get('score'),
          'coverage':health.get('coverage_label'),'period':(summary.get('finance_kpi') or {}).get('reporting_period_key'),
          'commitments':[{key:item.get(key) for key in ('kpi_id','actual','checkpoint','score','measurement_status','status_vs_path','metric_definition_version')} for item in health['commitments']]})
    return {'points':points,'definition':'History records processed source measurements. Reprocessing the same period is a revision, not a new day of performance.',
            'automatic_feed':'Not connected; changes arrive through the governed source-pack workflow.'}


@router.get('/api/operations/inference')
def inference(principal: dict[str,Any]=require_role('operator','reviewer','tenant_admin')):
    handle,failure=state_store.database_connection()
    if failure or handle is None:raise HTTPException(503,'Inference monitoring requires the durable database.')
    with handle as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('strategyos_inference_audit')")
            if cur.fetchone()[0] is None:return {'status':'no_observations','requests':0,'alerts':[]}
            cur.execute("""SELECT count(*) AS requests,count(*) FILTER (WHERE status='failed') AS failures,
                count(*) FILTER (WHERE status='budget_blocked') AS budget_blocks,
                count(*) FILTER (WHERE status='started' AND created_at<now()-interval '5 minutes') AS stalled,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms,
                coalesce(sum(reserved_units),0) AS reserved_units
                FROM strategyos_inference_audit WHERE tenant_key=%s AND created_at>now()-interval '24 hours'""",(principal['tenant_id'],))
            row=state_store.fetchone_dict(cur)
    alerts=[key for key in ('failures','budget_blocks','stalled') if row.get(key)]
    return {'status':'attention' if alerts else 'observed',**row,'alerts':alerts,
       'budget_basis':'Character-equivalent reservation units; not billable tokens or monetary cost.',
       'billing_cost':None,'billing_status':'No provider billing rates or usage receipts configured.',
       'retention':{'metadata_days':30,'encrypted_payload_days':7},
       'slo_status':'Measured observations; contractual SLO and target workload not yet agreed.'}
