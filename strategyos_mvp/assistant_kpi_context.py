"""Deterministic KPI context, independent of model availability or wording.

The UI supplies only a selected KPI key. Values and their provenance are read
again from the authorized snapshot; this is explicitly context, not a semantic
answer to the user's question.
"""
from .fact_rendering import fact_registry, render_selection
from .governed_finance import EVIDENCE_COMPONENTS, COMPONENT_CONTRACTS


def read_context(repository, *, run_id, key, context):
    components = EVIDENCE_COMPONENTS.get(key)
    if not components:
        raise ValueError('Select a supported KPI to open its verified figures.')
    contracts = {COMPONENT_CONTRACTS[c] for c in components}
    snapshot = repository.snapshot(f'run:{run_id}', context=context,
                                   metric_keys={metric for metric, _ in contracts})
    if snapshot.get('requires_resolution') or snapshot.get('requires_recompute'):
        raise PermissionError('These KPI figures need evidence review before they can be displayed.')
    records = [record for record in snapshot.get('records', [])
               if (record.get('metric_key'), record.get('claim_kind')) in contracts]
    registry = fact_registry(records)
    if not registry:
        raise LookupError('No verified figures are available for this KPI under your current access.')
    result = render_selection({'matched': True, 'fact_refs': list(registry)}, registry, run_id=run_id)
    providers = sorted({str((fact['record'].get('dimensions') or {}).get('source_contract_provider') or '').strip()
                        for fact in registry.values()} - {''})
    return {**result, 'status': 'ok', 'run_id': run_id, 'context_only': True,
            'determinism_tier': 'governed_context', 'kpi_key': key,
            'answer_caveat': 'Verified figures for the selected KPI. These provide context; the language answer to your question is not complete.',
            'answer': 'Verified figures for the selected KPI. These provide context; the language answer to your question is not complete.\n\n' + result['answer'],
            'analysis_as_of': snapshot.get('analysis_as_of'),
            'source_providers': providers,
            'response_sections': {}, 'executive_blocks': []}
