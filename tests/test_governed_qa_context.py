from __future__ import annotations

from strategyos_mvp.governed_qa_context import claim_backed_bundle, persisted_findings


def test_claim_backed_bundle_uses_only_authorized_snapshot_records():
    record = {
        "metric_key": "finance.transaction.amount",
        "claim_kind": "actual",
        "value": "125.50",
        "scale": "1",
        "unit": "SAR",
        "currency": "SAR",
        "subject": {"type": "ap_invoice", "key": "INV-7"},
        "dimensions": {
            "transaction_type": "ap_invoice",
            "counterparty_key": "V-9",
            "record": {
                "Invoice_ID": "INV-7",
                "Vendor_ID": "V-9",
                "Vendor_Name": "Approved Supplier",
                "Status": "Open",
            },
        },
        "sources": [
            {
                "source_key": "erp-finance",
                "origin_category": "internal_system",
                "original_uri": "02_ERP_Extracts/AP.xlsx",
            }
        ],
    }

    bundle = claim_backed_bundle([record])

    assert bundle.dataset_root.as_posix() == "governed-claim-ledger"
    assert bundle.evidence is None
    assert bundle.ap.to_dict("records") == [
        {
            "Invoice_ID": "INV-7",
            "Vendor_ID": "V-9",
            "Vendor_Name": "Approved Supplier",
            "Status": "Open",
            "Amount_SAR": 125.5,
        }
    ]
    assert bundle.ar.empty
    assert bundle.run_metadata == {
        "available_roles": ["ap_ledger"],
        "data_boundary": "authorized_claim_snapshot",
    }
    assert bundle.data_contracts["ap_ledger"]["source_key"] == "erp-finance"


def test_persisted_findings_fail_closed_on_invalid_enums():
    findings = persisted_findings(
        [
            {
                "finding_id": "finding-1",
                "title": "Governed finding",
                "confidence": "certain",
                "status": "auto-approved",
            }
        ]
    )

    assert findings[0].confidence == "LOW"
    assert findings[0].status == "draft"


def test_hydration_keeps_dashboard_records_but_separates_semantic_answer_scope(monkeypatch):
    from strategyos_mvp import api
    seen = []
    records = [{'metric_key': 'new.metric', 'value': '123'},
               {'metric_key': 'ceo.cash_floor', 'value': '456'}]
    class Repository:
        def snapshot(self, key, **kwargs):
            seen.append(kwargs)
            return {'records': records}
    monkeypatch.setattr(api, 'ClaimRepository', Repository)
    monkeypatch.setattr(api, '_assistant_claim_retrieval_plan', lambda *args, **kwargs: {
        'intent': 'facts', 'selected_metric_keys': frozenset({'new.metric'}),
        'metric_keys': frozenset({'new.metric', 'ceo.cash_floor'})})
    context = {'run_id':'run', 'summary':{'_claim_policy_context':{'tenant_id':'tenant-a'}}}
    result = api._hydrate_governed_qa_context(context,
        principal={'tenant_id':'tenant-a','subject':'reader','role':'executive'}, question='Natural question')
    assert seen[0]['context'].tenant_id == 'tenant-a'
    assert seen[0]['metric_keys'] == frozenset({'new.metric', 'ceo.cash_floor'})
    assert len(result['bundle'].authorized_claim_records) == 2
    assert result['bundle'].answer_metric_keys == frozenset({'new.metric'})


def test_hydration_returns_general_answer_without_loading_claim_values(monkeypatch):
    from types import SimpleNamespace
    from strategyos_mvp import api
    class Repository:
        def snapshot(self, *_args, **_kwargs):
            raise AssertionError('general routing must not load claim values')
    monkeypatch.setattr(api, 'ClaimRepository', Repository)
    monkeypatch.setattr(api, '_assistant_claim_retrieval_plan', lambda *args, **kwargs: {
        'intent': 'general', 'metric_keys': frozenset(),
        'answer': 'GDP means gross domestic product.',
    })
    monkeypatch.setattr(api.llm_qa, 'chat_status', lambda _: {
        'enabled': True, 'provider': 'openai-compatible', 'model': 'gpt-test',
    })
    monkeypatch.setattr(api, 'CONFIG', SimpleNamespace(
        llm_provider='openai-compatible', llm_model='gpt-test'))
    context = {'run_id': 'run', 'summary': {
        '_claim_policy_context': {'tenant_id': 'tenant-a'},
    }}
    result = api._hydrate_governed_qa_context(context,
        principal={'tenant_id': 'tenant-a', 'subject': 'reader', 'role': 'executive'},
        question='What is GDP?')
    assert result['assistant_data_intent'] == 'general'
    assert result['assistant_general_result']['answer'] == 'GDP means gross domestic product.'
    assert result['assistant_general_result']['citations'] == []
    assert result['data_boundary'] == 'no_company_evidence'
