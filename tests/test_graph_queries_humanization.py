from strategyos_mvp.graph_queries import Neo4jGraphSource


def test_vendor_collusion_clusters_answer_is_ceo_readable(monkeypatch):
    source = Neo4jGraphSource(driver_factory=lambda: None)
    monkeypatch.setattr(
        source,
        "_read",
        lambda *_args, **_kwargs: [
            {
                "left": {"node_key": "Vendor:V-1", "domain_label": "Vendor", "vendor_id": "V-1", "vendor_name": "Alpha LLC"},
                "right": {"node_key": "Vendor:V-2", "domain_label": "Vendor", "vendor_id": "V-2", "vendor_name": "Beta LLC"},
                "relationship_type": "SAME_BANK_ACCOUNT_AS",
                "findings": [
                    {"node_key": "Finding:F-001", "domain_label": "Finding", "finding_id": "F-001", "title": "Duplicate payouts", "recoverable_sar": 1200000},
                ],
                "evidence": [
                    {"node_key": "Evidence:03_Master_Data/Vendor_Master.xlsx", "domain_label": "Evidence", "source_path": "03_Master_Data/Vendor_Master.xlsx", "locator": "Vendor:V-1"},
                ],
            }
        ],
    )

    result = source.vendor_collusion_clusters("run-1")

    assert "Alpha LLC and Beta LLC" in result["answer"]
    assert "share same bank account as" in result["answer"].lower()
    assert "CEO implication" in result["answer"]
    assert result["citations"][0]["source_path"] == "03_Master_Data/Vendor_Master.xlsx"


def test_vendor_contract_gap_answer_names_vendors_and_amounts(monkeypatch):
    source = Neo4jGraphSource(driver_factory=lambda: None)
    monkeypatch.setattr(
        source,
        "_read",
        lambda *_args, **_kwargs: [
            {
                "vendor": {"node_key": "Vendor:V-1", "domain_label": "Vendor", "vendor_id": "V-1", "vendor_name": "Tamween Distribution"},
                "invoice_count": 4,
                "invoice_amount_sar": 8600000,
            },
            {
                "vendor": {"node_key": "Vendor:V-2", "domain_label": "Vendor", "vendor_id": "V-2", "vendor_name": "Alpha Medical"},
                "invoice_count": 2,
                "invoice_amount_sar": 1200000,
            },
        ],
    )

    result = source.vendor_contract_gaps("run-1")

    assert "Tamween Distribution" in result["answer"]
    assert "SAR 8,600,000.00" in result["answer"]
    assert "CEO implication" in result["answer"]
