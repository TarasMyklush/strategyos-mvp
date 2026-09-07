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
