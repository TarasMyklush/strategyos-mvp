from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from strategyos_mvp.oracle_finance import (
    BUFlexfieldMappingConfig,
    build_oracle_leakage_review_payload,
    compute_oracle_pilot_kpis,
    compute_oracle_pilot_leakage,
    ingest_oracle_pilot_extracts,
    load_pilot_extract_batch,
)


def _mapping() -> BUFlexfieldMappingConfig:
    return BUFlexfieldMappingConfig(
        segment_name="segment2",
        segment_index=1,
        value_to_bu={"BU01": "Consumer", "BU02": "Healthcare"},
        default_bu="Corporate",
    )


def _phase13_snapshot():
    return ingest_oracle_pilot_extracts(
        load_pilot_extract_batch(
            {
                "GL": [
                    {
                        "natural_key": "gl-revenue-june",
                        "fact_type": "revenue",
                        "amount": "10000",
                        "currency": "SAR",
                        "period_name": "2026-06",
                        "period_start": "2026-06-01",
                        "period_end": "2026-06-30",
                        "flexfield_segments": ["COMP", "BU01", "CC100"],
                    },
                    {
                        "natural_key": "gl-opex-june",
                        "fact_type": "operating_cost",
                        "amount": "5000",
                        "currency": "SAR",
                        "period_name": "2026-06",
                        "period_start": "2026-06-01",
                        "period_end": "2026-06-30",
                        "flexfield_segments": ["COMP", "BU01", "CC100"],
                    },
                ],
                "AP": [
                    {
                        "natural_key": "ap-dup-1",
                        "fact_type": "payment",
                        "amount": "1200",
                        "payment_amount": "1200",
                        "currency": "SAR",
                        "invoice_num": "DUP-001",
                        "invoice_date": "2026-06-05",
                        "payment_date": "2026-06-10",
                        "payment_reference": "PAY-001",
                        "vendor_id": "V100",
                        "vendor_name": "Alpha Supplies",
                    },
                    {
                        "natural_key": "ap-dup-2",
                        "fact_type": "payment",
                        "amount": "1200",
                        "payment_amount": "1200",
                        "currency": "SAR",
                        "invoice_num": "DUP-001",
                        "invoice_date": "2026-06-05",
                        "payment_date": "2026-06-12",
                        "payment_reference": "PAY-002",
                        "vendor_id": "V100",
                        "vendor_name": "Alpha Supplies",
                    },
                    {
                        "natural_key": "ap-ent-1",
                        "fact_type": "payment",
                        "amount": "800",
                        "payment_amount": "800",
                        "currency": "SAR",
                        "invoice_num": "ENT-001",
                        "invoice_date": "2026-06-07",
                        "payment_date": "2026-06-14",
                        "payment_reference": "PAY-ENT-1",
                        "vendor_id": "V201",
                        "vendor_name": "Beta Industrial",
                        "vendor_tax_id": "TAX-8899",
                    },
                    {
                        "natural_key": "ap-ent-2",
                        "fact_type": "payment",
                        "amount": "800",
                        "payment_amount": "800",
                        "currency": "SAR",
                        "invoice_num": "ENT-001",
                        "invoice_date": "2026-06-07",
                        "payment_date": "2026-06-15",
                        "payment_reference": "PAY-ENT-2",
                        "vendor_id": "V202",
                        "vendor_name": "Beta Industrial LLC",
                        "vendor_tax_id": "TAX-8899",
                    },
                    {
                        "natural_key": "ap-off-1",
                        "fact_type": "invoice",
                        "amount": "1500",
                        "invoice_amount": "1500",
                        "currency": "SAR",
                        "invoice_num": "OFF-001",
                        "invoice_date": "2026-06-09",
                        "vendor_id": "V300",
                        "vendor_name": "Gamma Tech",
                        "category": "IT",
                        "quantity": "10",
                    },
                    {
                        "natural_key": "ap-pv-1",
                        "fact_type": "invoice",
                        "amount": "1200",
                        "invoice_amount": "1200",
                        "currency": "SAR",
                        "invoice_num": "PV-001",
                        "invoice_date": "2026-06-11",
                        "vendor_id": "V400",
                        "vendor_name": "Delta Parts",
                        "category": "MRO",
                        "quantity": "10",
                        "invoice_unit_price": "120",
                        "po_reference": "PO-400",
                    },
                    {
                        "natural_key": "ap-disc-1",
                        "fact_type": "invoice",
                        "amount": "1000",
                        "invoice_amount": "1000",
                        "currency": "SAR",
                        "invoice_num": "DISC-001",
                        "invoice_date": "2026-06-01",
                        "payment_date": "2026-06-20",
                        "vendor_id": "V500",
                        "vendor_name": "Epsilon Services",
                        "discount_pct": "2",
                        "discount_due_date": "2026-06-05",
                    },
                    {
                        "natural_key": "ap-balance-1",
                        "fact_type": "accounts_payable_balance",
                        "amount": "6200",
                        "currency": "SAR",
                        "event_date": "2026-06-30",
                    },
                    {
                        "natural_key": "ap-fx-1",
                        "fact_type": "invoice",
                        "amount": "3900",
                        "invoice_amount": "3900",
                        "currency": "USD",
                        "invoice_num": "FX-001",
                        "invoice_date": "2026-06-16",
                        "vendor_id": "V700",
                        "vendor_name": "Zeta Global",
                        "foreign_amount": "1000",
                        "applied_fx_rate": "3.90",
                    },
                    {
                        "natural_key": "ap-credit-1",
                        "fact_type": "credit_balance",
                        "amount": "-250",
                        "currency": "SAR",
                        "vendor_id": "V800",
                        "vendor_name": "Eta Logistics",
                        "credit_reference": "CR-001",
                        "credit_balance_amount": "250",
                        "last_activity_date": "2026-02-01",
                        "credit_status": "open",
                    },
                ],
                "PO": [
                    {
                        "natural_key": "po-400",
                        "fact_type": "purchase_order_line",
                        "amount": "850",
                        "currency": "SAR",
                        "event_date": "2026-06-02",
                        "po_reference": "PO-400",
                        "po_unit_price": "85",
                        "quantity": "10",
                        "vendor_id": "V400",
                        "vendor_name": "Delta Parts",
                        "category": "MRO",
                    }
                ],
            }
        ),
        bu_mapping=_mapping(),
        manual_inputs=[
            {
                "input_key": "contracts-june",
                "input_type": "contract_registry",
                "input_name": "June contract registry",
                "storage_kind": "file",
                "period_key": "2026-06",
                "contracts": [
                    {
                        "contract_id": "C-300",
                        "vendor_id": "V300",
                        "vendor_name": "Gamma Tech",
                        "category": "IT",
                        "start_date": "2026-01-01",
                        "end_date": "2026-12-31",
                        "unit_price": "100",
                    },
                    {
                        "contract_id": "C-600",
                        "vendor_id": "V600",
                        "vendor_name": "Theta Software",
                        "auto_renewal": True,
                        "renewal_date": "2026-06-18",
                        "previous_annual_value": "1000",
                        "renewed_annual_value": "1300",
                    },
                ],
                "line_items": [
                    {
                        "contract_id": "C-300-BENCH",
                        "vendor_id": "V300",
                        "vendor_name": "Gamma Tech",
                        "category": "IT",
                        "off_contract_savings_pct": "10",
                    }
                ],
            },
            {
                "input_key": "hedges-june",
                "input_type": "hedge_register",
                "input_name": "June hedge register",
                "storage_kind": "file",
                "period_key": "2026-06",
                "hedges": [
                    {
                        "hedge_id": "H-700",
                        "invoice_num": "FX-001",
                        "vendor_id": "V700",
                        "currency": "USD",
                        "hedged_rate": "3.75",
                    }
                ],
            },
        ],
    )


def test_phase13_leakage_engine_covers_all_patterns_ranks_by_recoverable_value_and_attaches_evidence():
    snapshot = _phase13_snapshot()

    review = compute_oracle_pilot_leakage(snapshot, reporting_period_key="2026-06")
    payload = build_oracle_leakage_review_payload(review)

    assert review.authoritative is True
    assert len(review.findings) == 8
    assert {finding.pattern_type for finding in review.findings} == {
        "duplicate_payment",
        "entity_resolution_duplicate",
        "off_contract_spend",
        "price_variance",
        "missed_early_pay_discount",
        "auto_renewal_escalation",
        "fx_hedge_not_applied",
        "dormant_credit_balance",
    }
    assert [finding.pattern_type for finding in review.findings] == [
        "duplicate_payment",
        "entity_resolution_duplicate",
        "off_contract_spend",
        "price_variance",
        "auto_renewal_escalation",
        "dormant_credit_balance",
        "fx_hedge_not_applied",
        "missed_early_pay_discount",
    ]
    assert [finding.priority_rank for finding in review.findings] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert review.findings[0].recoverable_sar == Decimal("1200")
    assert review.findings[1].recoverable_sar == Decimal("800")
    assert review.findings[2].recoverable_sar == Decimal("500")
    assert review.findings[3].recoverable_sar == Decimal("350")
    assert review.findings[4].recoverable_sar == Decimal("300")
    assert review.findings[5].recoverable_sar == Decimal("250")
    assert review.findings[6].recoverable_sar == Decimal("150.00")
    assert review.findings[7].recoverable_sar == Decimal("20.00")
    assert review.total_recoverable_sar == Decimal("3570.00")
    assert all(finding.evidence for finding in review.findings)
    assert any(item.source_kind == "manual_input" for item in review.findings[2].evidence)
    assert any(item.source_kind == "fact" for item in review.findings[3].evidence)

    assert payload["derived_from"] == "deterministic_oracle_leakage_engine"
    assert payload["ranking_basis"] == "recoverable_sar_desc"
    assert payload["total_findings"] == 8
    assert payload["total_recoverable_sar"] == "3570"
    assert payload["reviewer_workflow"]["order_by"] == "recoverable_sar_desc"
    assert "challenge_points" in payload["reviewer_workflow"]["auditor_fields"]
    assert payload["findings"][0]["evidence"][0]["locator"].startswith("AP:")
    assert payload["findings"][2]["evidence"][1]["source_kind"] == "manual_input"


def test_phase13_leakage_engine_does_not_regress_kpi_computation_boundary():
    snapshot = _phase13_snapshot()

    computation = compute_oracle_pilot_kpis(snapshot, reporting_period_key="2026-06")

    assert computation.metrics["revenue_attainment_pct"] is None
    assert computation.metrics["dpo_days"] == Decimal("37.2")
    assert computation.computation_boundary.startswith("Deterministic Oracle KPI computation only")


def test_phase13_duplicate_payment_uses_same_amount_chain_for_grouping_and_recovery_math():
    snapshot = ingest_oracle_pilot_extracts(
        load_pilot_extract_batch(
            {
                "AP": [
                    {"natural_key": "dup-a", "fact_type": "payment", "amount_paid": "500", "currency": "SAR", "invoice_num": "DUP-AMOUNT", "payment_date": "2026-06-10", "vendor_id": "V100"},
                    {"natural_key": "dup-b", "fact_type": "payment", "amount_paid": "500", "currency": "SAR", "invoice_num": "DUP-AMOUNT", "payment_date": "2026-06-11", "vendor_id": "V100"},
                ]
            }
        ),
        bu_mapping=_mapping(),
    )

    review = compute_oracle_pilot_leakage(snapshot, reporting_period_key="2026-06")

    duplicate = next(finding for finding in review.findings if finding.pattern_type == "duplicate_payment")
    assert duplicate.recoverable_sar == Decimal("500")


def test_phase13_fx_hedge_detector_handles_divisor_quote_direction():
    snapshot = ingest_oracle_pilot_extracts(
        load_pilot_extract_batch(
            {
                "AP": [
                    {
                        "natural_key": "fx-divisor",
                        "fact_type": "invoice",
                        "amount": "200",
                        "invoice_amount": "200",
                        "currency": "JPY",
                        "invoice_num": "FX-DIV-001",
                        "invoice_date": "2026-06-16",
                        "vendor_id": "V700",
                        "foreign_amount": "1000",
                        "applied_fx_rate": "5",
                    }
                ]
            }
        ),
        bu_mapping=_mapping(),
        manual_inputs=[{"input_key": "hedges-june", "input_type": "hedge_register", "input_name": "June hedge register", "storage_kind": "file", "period_key": "2026-06", "hedges": [{"hedge_id": "H-700", "invoice_num": "FX-DIV-001", "vendor_id": "V700", "currency": "JPY", "hedged_rate": "10"}]}],
        reporting_currency="USD",
    )

    review = compute_oracle_pilot_leakage(snapshot, reporting_period_key="2026-06")

    fx_finding = next(finding for finding in review.findings if finding.pattern_type == "fx_hedge_not_applied")
    assert fx_finding.recoverable_sar == Decimal("100")
    assert fx_finding.calculation["quote_direction"] == "foreign_per_reporting_divisor"


def test_phase13_off_contract_detector_does_not_inflate_negative_quantities():
    snapshot = ingest_oracle_pilot_extracts(
        load_pilot_extract_batch(
            {
                "AP": [
                    {
                        "natural_key": "off-negative-qty",
                        "fact_type": "invoice",
                        "amount": "1000",
                        "invoice_amount": "1000",
                        "currency": "SAR",
                        "invoice_num": "OFF-NEG-001",
                        "invoice_date": "2026-06-09",
                        "vendor_id": "V300",
                        "vendor_name": "Gamma Tech",
                        "category": "IT",
                        "quantity": "-10",
                    }
                ]
            }
        ),
        bu_mapping=_mapping(),
        manual_inputs=[{"input_key": "contracts-june", "input_type": "contract_registry", "input_name": "June contract registry", "storage_kind": "file", "period_key": "2026-06", "contracts": [{"contract_id": "C-300", "vendor_id": "V300", "vendor_name": "Gamma Tech", "category": "IT", "start_date": "2026-01-01", "end_date": "2026-12-31", "unit_price": "100"}]}],
    )

    review = compute_oracle_pilot_leakage(snapshot, reporting_period_key="2026-06")

    assert all(finding.pattern_type != "off_contract_spend" for finding in review.findings)


def test_phase13_plan_data_keeps_closed_leakage_phase_truthful_while_hosted_fixup_stays_open():
    plan_file = (
        Path(__file__).resolve().parents[1]
        / "strategyos_mvp"
        / "static"
        / "plan_data.js"
    )
    text = plan_file.read_text(encoding="utf-8")
    assert 'updated: "2026-06-30"' in text
    assert 'Reviewed backend correctness sweep shipped' in text
    assert 'FX hedge quote direction inferred instead of assumed.' in text
    assert 'Negative-quantity inflation blocked in recoverable math.' in text
    assert 'id: "DONE-007"' in text
    assert 'Hosted /public/runs/latest/audit-summary now returns the sanitized public-safe payload' in text
    assert 'hosted findings remain scrubbed to board-safe signal labels.' in text
