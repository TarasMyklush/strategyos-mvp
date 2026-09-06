"""Exact reporting periods survive SQL and semantic candidate reauthorization."""
from datetime import UTC, date, datetime

import pytest

from strategyos_mvp.claim_retrieval import search_claims
from strategyos_mvp.source_claims import ClaimDraft, ClaimQuery
from tests.test_cross_source_postgres_e2e import ledger
from tests.test_tabular_claims_postgres_e2e import setup_intake

pytestmark = pytest.mark.integration


def test_exact_period_filters_unknown_overlapping_and_semantic_candidates(ledger):
    repo,context,occurrence,_,_ = setup_intake(ledger)
    ids = []
    for start,end in [(date(2026,6,1),date(2026,6,30)),
                      (date(2026,1,1),date(2026,6,30)),(None,None)]:
        draft = ClaimDraft(tenant_id=context.tenant_id,assertion_namespace='period-proof',
            subject_type='enterprise',subject_key='group',metric_key='test.period',
            claim_kind='actual',production_method='imported',value_numeric=10,
            unit='SAR',currency='SAR',period_start=start,period_end=end,
            fiscal_calendar='group-fiscal-v1',source_occurrence_keys=(occurrence,))
        ids.append(repo.record_claim(draft,traceability='present')['claim_revision_id'])
    query = ClaimQuery(tenant_id=context.tenant_id,metric_key='test.period',
        purpose=context.purpose,as_of_at=datetime.now(UTC),allowed_claim_kinds=frozenset({'actual'}),
        period_start=date(2026,6,1),period_end=date(2026,6,30),fiscal_calendar='group-fiscal-v1')
    assert [row['claim_revision_id'] for row in repo.query(query,context=context)] == ids[:1]
    results = search_claims('period proof',query=query,context=context,repository=repo,
        candidates=lambda *args,**kwargs:list(reversed(ids)))
    assert [row['claim_revision_id'] for row in results] == ids[:1]
