from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Mapping, Sequence


OracleModule = Literal["GL", "AR", "AP", "CE", "FA", "PO", "INV"]
Cadence = Literal["daily", "weekly", "monthly", "quarterly"]
ManualInputType = Literal[
    "budget_plan",
    "hedge_register",
    "contract_registry",
    "covenant_terms",
    "board_floor",
    "commentary",
]
StorageKind = Literal["file", "manual"]

ORACLE_MODULES: tuple[OracleModule, ...] = ("GL", "AR", "AP", "CE", "FA", "PO", "INV")
MANUAL_INPUT_TYPES: tuple[ManualInputType, ...] = (
    "budget_plan",
    "hedge_register",
    "contract_registry",
    "covenant_terms",
    "board_floor",
    "commentary",
)
DEFAULT_CADENCE_BY_MODULE: dict[OracleModule, Cadence] = {
    "GL": "monthly",
    "AR": "daily",
    "AP": "daily",
    "CE": "daily",
    "FA": "quarterly",
    "PO": "weekly",
    "INV": "weekly",
}
MANUAL_INPUT_DEFAULT_CADENCE: dict[ManualInputType, Cadence] = {
    "budget_plan": "monthly",
    "hedge_register": "weekly",
    "contract_registry": "monthly",
    "covenant_terms": "quarterly",
    "board_floor": "daily",
    "commentary": "monthly",
}


@dataclass(frozen=True)
class OracleFieldMapping:
    target_field: str
    source_field: str
    required: bool = False
    notes: str | None = None


@dataclass(frozen=True)
class OracleConnectorDefinition:
    module: OracleModule
    representative_tables: tuple[str, ...]
    mappings: tuple[OracleFieldMapping, ...]
    loader_kind: str = "pilot_fixture"
    notes: str | None = None

    def mapping_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for table in self.representative_tables:
            for mapping in self.mappings:
                records.append(
                    {
                        "module": self.module,
                        "mapping_type": "canonical_field",
                        "source_table": table,
                        "source_field": mapping.source_field,
                        "target_field": mapping.target_field,
                        "required": mapping.required,
                        "notes": mapping.notes or self.notes,
                    }
                )
        return records


@dataclass(frozen=True)
class BUFlexfieldMappingConfig:
    segment_name: str
    segment_index: int
    value_to_bu: dict[str, str]
    default_bu: str | None = None

    def resolve(
        self,
        segments: Sequence[str] | str | None,
        *,
        fallback_cost_centre: str | None = None,
    ) -> tuple[str | None, str | None, str | None]:
        parsed = _normalize_segments(segments)
        if self.segment_index < 0 or self.segment_index >= len(parsed):
            return self.default_bu, fallback_cost_centre, None
        raw_value = parsed[self.segment_index]
        key = raw_value.strip().upper()
        return self.value_to_bu.get(key, self.default_bu), raw_value, self.segment_name

    def as_mapping_record(self) -> dict[str, Any]:
        return {
            "module": "GL",
            "mapping_type": "bu_flexfield_segment",
            "source_table": "GL_CODE_COMBINATIONS",
            "source_field": self.segment_name,
            "target_field": "business_unit",
            "required": True,
            "notes": f"segment_index={self.segment_index}",
            "attributes": {
                "default_bu": self.default_bu,
                "segment_index": self.segment_index,
                "value_to_bu": dict(self.value_to_bu),
            },
        }


@dataclass(frozen=True)
class PeriodMetadata:
    period_key: str
    label: str
    cadence: Cadence
    period_start: date | None = None
    period_end: date | None = None
    source_period_name: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FXRateRecord:
    rate_key: str
    source_currency: str
    reporting_currency: str
    rate_source: str
    rate_date: date
    rate_value: Decimal
    fallback_allowed: bool = False
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CanonicalFinanceFact:
    natural_key: str
    module: OracleModule
    fact_type: str
    period_key: str
    cadence: Cadence
    amount_value: Decimal | None = None
    currency: str | None = None
    reporting_currency: str | None = None
    bu_code: str | None = None
    cost_centre: str | None = None
    account_code: str | None = None
    source_reference: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ManualInputRecord:
    input_key: str
    input_type: ManualInputType
    input_name: str
    storage_kind: StorageKind
    cadence: Cadence
    period_key: str | None = None
    owner_role: str | None = None
    source_uri: str | None = None
    status: str = "active"
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OracleExtractBatch:
    extracts: dict[OracleModule, list[dict[str, Any]]] = field(default_factory=dict)

    def module_rows(self, module: OracleModule) -> list[dict[str, Any]]:
        return list(self.extracts.get(module, []))


@dataclass(frozen=True)
class OracleCanonicalSnapshot:
    connectors: tuple[OracleConnectorDefinition, ...]
    connector_mappings: tuple[dict[str, Any], ...]
    periods: tuple[PeriodMetadata, ...]
    facts: tuple[CanonicalFinanceFact, ...]
    fx_rates: tuple[FXRateRecord, ...]
    manual_inputs: tuple[ManualInputRecord, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OracleKpiComputation:
    reporting_period_key: str
    reporting_cadence: Cadence
    period_start: date
    period_end: date
    period_days: int
    metrics: dict[str, Decimal | None]
    components: dict[str, Decimal | None]
    source_fact_types: dict[str, tuple[str, ...]]
    manual_input_keys: tuple[str, ...]
    authoritative: bool = True
    computation_boundary: str = (
        "Deterministic Oracle KPI computation only. Any narration is downstream and non-authoritative."
    )


@dataclass(frozen=True)
class OracleLeakageEvidence:
    source_kind: Literal["fact", "manual_input"]
    source_key: str
    locator: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OracleLeakageFinding:
    finding_id: str
    title: str
    pattern_type: str
    vendor_id: str
    vendor_name: str
    leakage_sar: Decimal
    recoverable_sar: Decimal
    confidence: Literal["high", "medium", "low"]
    rationale: str
    calculation: dict[str, Any]
    evidence: tuple[OracleLeakageEvidence, ...]
    challenge_points: tuple[str, ...]
    review_status: Literal["pending_review", "challenged", "approved", "rejected"] = "pending_review"
    priority_rank: int = 0


@dataclass(frozen=True)
class OracleLeakageReview:
    reporting_period_key: str
    reporting_cadence: Cadence
    period_start: date
    period_end: date
    findings: tuple[OracleLeakageFinding, ...]
    ranking_basis: str
    total_recoverable_sar: Decimal
    authoritative: bool = True
    computation_boundary: str = (
        "Deterministic Oracle leakage rules compute findings and values. Narrative may explain later but must not decide the math or trigger logic."
    )


def snapshot_summary(snapshot: OracleCanonicalSnapshot) -> dict[str, Any]:
    facts_by_module: dict[str, int] = {module: 0 for module in ORACLE_MODULES}
    for fact in snapshot.facts:
        facts_by_module[fact.module] = facts_by_module.get(fact.module, 0) + 1
    manual_inputs_by_type: dict[str, int] = {input_type: 0 for input_type in MANUAL_INPUT_TYPES}
    for record in snapshot.manual_inputs:
        manual_inputs_by_type[record.input_type] = manual_inputs_by_type.get(record.input_type, 0) + 1
    return {
        "connector_mappings": len(snapshot.connector_mappings),
        "periods": len(snapshot.periods),
        "facts": len(snapshot.facts),
        "facts_by_module": facts_by_module,
        "fx_rates": len(snapshot.fx_rates),
        "manual_inputs": len(snapshot.manual_inputs),
        "manual_inputs_by_type": manual_inputs_by_type,
        "modules_loaded": dict(snapshot.metadata.get("modules_loaded", {})),
        "reporting_currency": snapshot.metadata.get("reporting_currency"),
    }


def default_oracle_connector_definitions() -> tuple[OracleConnectorDefinition, ...]:
    return (
        OracleConnectorDefinition(
            module="GL",
            representative_tables=("GL_BALANCES", "GL_CODE_COMBINATIONS", "GL_DAILY_RATES", "GL_PERIODS"),
            mappings=(
                OracleFieldMapping("account_code", "account_code", required=True),
                OracleFieldMapping("amount", "period_net_amount", required=True),
                OracleFieldMapping("period_name", "period_name", required=True),
                OracleFieldMapping("flexfield_segments", "accounting_flexfield_segments", required=True),
            ),
            notes="Pilot fixture mapping for GL balances, periods, and rates.",
        ),
        OracleConnectorDefinition(
            module="AR",
            representative_tables=("AR_PAYMENT_SCHEDULES_ALL", "AR_CASH_RECEIPTS_ALL", "HZ_CUST_ACCOUNTS"),
            mappings=(
                OracleFieldMapping("invoice_reference", "customer_trx_number", required=True),
                OracleFieldMapping("amount", "amount_due_remaining", required=True),
                OracleFieldMapping("event_date", "trx_date"),
                OracleFieldMapping("customer_key", "cust_account_id", required=True),
            ),
            notes="Pilot fixture mapping for AR aging, collections, and customer concentration.",
        ),
        OracleConnectorDefinition(
            module="AP",
            representative_tables=("AP_INVOICES_ALL", "AP_PAYMENT_SCHEDULES_ALL", "AP_SUPPLIERS"),
            mappings=(
                OracleFieldMapping("invoice_reference", "invoice_num", required=True),
                OracleFieldMapping("amount", "amount_remaining", required=True),
                OracleFieldMapping("event_date", "invoice_date"),
                OracleFieldMapping("supplier_key", "vendor_id", required=True),
            ),
            notes="Pilot fixture mapping for AP aging, disbursements, and supplier exposure.",
        ),
        OracleConnectorDefinition(
            module="CE",
            representative_tables=("CE_BANK_ACCOUNTS", "CE_STATEMENT_BALANCES"),
            mappings=(
                OracleFieldMapping("bank_account", "bank_account_name", required=True),
                OracleFieldMapping("amount", "available_balance", required=True),
                OracleFieldMapping("as_of_date", "balance_date", required=True),
            ),
            notes="Pilot fixture mapping for bank balances and liquidity position.",
        ),
        OracleConnectorDefinition(
            module="FA",
            representative_tables=("FA_BOOKS", "FA_ADDITIONS_B"),
            mappings=(
                OracleFieldMapping("asset_key", "asset_number", required=True),
                OracleFieldMapping("amount", "net_book_value", required=True),
                OracleFieldMapping("event_date", "date_placed_in_service"),
            ),
            notes="Pilot fixture mapping for asset books and capital base facts.",
        ),
        OracleConnectorDefinition(
            module="PO",
            representative_tables=("PO_HEADERS_ALL", "PO_LINES_ALL", "PO_DISTRIBUTIONS_ALL"),
            mappings=(
                OracleFieldMapping("po_reference", "segment1", required=True),
                OracleFieldMapping("amount", "amount_ordered", required=True),
                OracleFieldMapping("event_date", "creation_date"),
                OracleFieldMapping("supplier_key", "vendor_id"),
            ),
            notes="Pilot fixture mapping for purchasing commitments and contract exposure.",
        ),
        OracleConnectorDefinition(
            module="INV",
            representative_tables=("MTL_ONHAND_QUANTITIES_DETAIL", "MTL_SYSTEM_ITEMS_B"),
            mappings=(
                OracleFieldMapping("inventory_item", "inventory_item_id", required=True),
                OracleFieldMapping("amount", "inventory_value", required=True),
                OracleFieldMapping("event_date", "snapshot_date"),
            ),
            notes="Pilot fixture mapping for inventory holdings and DIO support.",
        ),
    )


def load_pilot_extract_batch(fixtures: Mapping[str, Sequence[Mapping[str, Any]]]) -> OracleExtractBatch:
    extracts: dict[OracleModule, list[dict[str, Any]]] = {}
    for module in ORACLE_MODULES:
        rows = fixtures.get(module, ())
        extracts[module] = [dict(row) for row in rows]
    return OracleExtractBatch(extracts=extracts)


def register_manual_inputs(
    entries: Sequence[Mapping[str, Any]] | None,
) -> tuple[ManualInputRecord, ...]:
    if not entries:
        return tuple()
    records: list[ManualInputRecord] = []
    for index, entry in enumerate(entries, start=1):
        input_type = str(entry.get("input_type") or "").strip()
        if input_type not in MANUAL_INPUT_TYPES:
            raise ValueError(f"Unsupported manual input type: {input_type}")
        cadence = str(entry.get("cadence") or MANUAL_INPUT_DEFAULT_CADENCE[input_type])
        input_name = str(entry.get("input_name") or input_type).strip()
        record = ManualInputRecord(
            input_key=str(entry.get("input_key") or f"{input_type}:{index}"),
            input_type=input_type,
            input_name=input_name,
            storage_kind=str(entry.get("storage_kind") or "file"),
            cadence=cadence,
            period_key=_text(entry.get("period_key")),
            owner_role=_text(entry.get("owner_role")),
            source_uri=_text(entry.get("source_uri")),
            status=str(entry.get("status") or "active"),
            attributes={
                key: value
                for key, value in dict(entry).items()
                if key
                not in {
                    "input_key",
                    "input_type",
                    "input_name",
                    "storage_kind",
                    "cadence",
                    "period_key",
                    "owner_role",
                    "source_uri",
                    "status",
                }
            },
        )
        records.append(record)
    return tuple(records)


def ingest_oracle_pilot_extracts(
    extract_batch: OracleExtractBatch,
    *,
    bu_mapping: BUFlexfieldMappingConfig,
    manual_inputs: Sequence[Mapping[str, Any]] | None = None,
    reporting_currency: str = "SAR",
) -> OracleCanonicalSnapshot:
    connectors = default_oracle_connector_definitions()
    periods: dict[str, PeriodMetadata] = {}
    facts: list[CanonicalFinanceFact] = []
    fx_rates: list[FXRateRecord] = []

    for connector in connectors:
        rows = extract_batch.module_rows(connector.module)
        for index, row in enumerate(rows, start=1):
            record_type = str(row.get("record_type") or "fact").strip().lower()
            if connector.module == "GL" and record_type == "fx_rate":
                fx_rates.append(_map_fx_rate(row, index, reporting_currency=reporting_currency))
                continue
            fact = _map_fact(
                connector.module,
                row,
                index=index,
                bu_mapping=bu_mapping,
                reporting_currency=reporting_currency,
            )
            facts.append(fact)
            periods.setdefault(
                fact.period_key,
                _period_from_row(
                    row,
                    period_key=fact.period_key,
                    cadence=fact.cadence,
                ),
            )

    manual_input_records = register_manual_inputs(manual_inputs)
    connector_mappings = [bu_mapping.as_mapping_record()]
    for connector in connectors:
        connector_mappings.extend(connector.mapping_records())

    for record in manual_input_records:
        if record.period_key and record.period_key not in periods:
            periods[record.period_key] = PeriodMetadata(
                period_key=record.period_key,
                label=record.period_key,
                cadence=record.cadence,
            )

    return OracleCanonicalSnapshot(
        connectors=connectors,
        connector_mappings=tuple(connector_mappings),
        periods=tuple(periods.values()),
        facts=tuple(facts),
        fx_rates=tuple(fx_rates),
        manual_inputs=manual_input_records,
        metadata={
            "reporting_currency": reporting_currency,
            "modules_loaded": {
                module: len(extract_batch.module_rows(module)) for module in ORACLE_MODULES
            },
        },
    )


def snapshot_payload(snapshot: OracleCanonicalSnapshot) -> dict[str, Any]:
    return {
        "connectors": [asdict(item) for item in snapshot.connectors],
        "connector_mappings": list(snapshot.connector_mappings),
        "periods": [asdict(item) for item in snapshot.periods],
        "facts": [asdict(item) for item in snapshot.facts],
        "fx_rates": [asdict(item) for item in snapshot.fx_rates],
        "manual_inputs": [asdict(item) for item in snapshot.manual_inputs],
        "metadata": dict(snapshot.metadata),
    }


def compute_oracle_pilot_kpis(
    snapshot: OracleCanonicalSnapshot,
    *,
    reporting_period_key: str,
    reporting_cadence: Cadence | None = None,
) -> OracleKpiComputation:
    period_lookup = {period.period_key: period for period in snapshot.periods}
    period = period_lookup.get(reporting_period_key)
    resolved_cadence = reporting_cadence or (period.cadence if period else _infer_cadence_from_period_key(reporting_period_key))
    period_start, period_end = _resolve_period_bounds(
        reporting_period_key,
        resolved_cadence,
        period_start=period.period_start if period else None,
        period_end=period.period_end if period else None,
    )
    period_days = (period_end - period_start).days + 1

    revenue = _sum_metric_facts(
        snapshot,
        reporting_period_key=reporting_period_key,
        reporting_cadence=resolved_cadence,
        period_start=period_start,
        period_end=period_end,
        fact_types=("revenue",),
    )
    ebitda = _sum_metric_facts(
        snapshot,
        reporting_period_key=reporting_period_key,
        reporting_cadence=resolved_cadence,
        period_start=period_start,
        period_end=period_end,
        fact_types=("ebitda",),
    )
    operating_cost = _sum_metric_facts(
        snapshot,
        reporting_period_key=reporting_period_key,
        reporting_cadence=resolved_cadence,
        period_start=period_start,
        period_end=period_end,
        fact_types=("operating_cost", "opex", "operating_expense"),
    )
    cash_balance = _latest_metric_fact(
        snapshot,
        reporting_period_key=reporting_period_key,
        reporting_cadence=resolved_cadence,
        period_start=period_start,
        period_end=period_end,
        fact_types=("cash_balance",),
    )
    receivables = _latest_metric_fact(
        snapshot,
        reporting_period_key=reporting_period_key,
        reporting_cadence=resolved_cadence,
        period_start=period_start,
        period_end=period_end,
        fact_types=("accounts_receivable_balance", "ar_open_balance", "receivables_balance"),
    )
    payables = _latest_metric_fact(
        snapshot,
        reporting_period_key=reporting_period_key,
        reporting_cadence=resolved_cadence,
        period_start=period_start,
        period_end=period_end,
        fact_types=("accounts_payable_balance", "ap_open_balance", "payables_balance"),
    )
    inventory = _latest_metric_fact(
        snapshot,
        reporting_period_key=reporting_period_key,
        reporting_cadence=resolved_cadence,
        period_start=period_start,
        period_end=period_end,
        fact_types=("inventory_balance", "working_capital_inventory", "inventory_on_hand"),
    )
    debt_balance = _latest_metric_fact(
        snapshot,
        reporting_period_key=reporting_period_key,
        reporting_cadence=resolved_cadence,
        period_start=period_start,
        period_end=period_end,
        fact_types=("debt_balance", "borrowings", "loan_balance"),
    )

    budget_inputs = _matching_manual_inputs(
        snapshot.manual_inputs,
        input_type="budget_plan",
        reporting_period_key=reporting_period_key,
        reporting_cadence=resolved_cadence,
        period_start=period_start,
        period_end=period_end,
    )
    board_floor_inputs = _matching_manual_inputs(
        snapshot.manual_inputs,
        input_type="board_floor",
        reporting_period_key=reporting_period_key,
        reporting_cadence=resolved_cadence,
        period_start=period_start,
        period_end=period_end,
    )
    covenant_inputs = _matching_manual_inputs(
        snapshot.manual_inputs,
        input_type="covenant_terms",
        reporting_period_key=reporting_period_key,
        reporting_cadence=resolved_cadence,
        period_start=period_start,
        period_end=period_end,
    )

    revenue_plan = _manual_decimal(
        budget_inputs,
        aliases=("revenue", "revenue_plan", "planned_revenue"),
    )
    ebitda_plan = _manual_decimal(
        budget_inputs,
        aliases=("ebitda", "ebitda_plan", "planned_ebitda"),
    )
    operating_cost_plan = _manual_decimal(
        budget_inputs,
        aliases=("operating_cost", "operating_cost_plan", "planned_operating_cost", "opex", "opex_plan"),
    )
    board_floor = _manual_decimal(
        board_floor_inputs,
        aliases=("board_floor", "cash_floor", "minimum_cash"),
    )
    covenant_limit = _manual_decimal(
        covenant_inputs,
        aliases=("max_net_debt_to_ebitda", "net_debt_to_ebitda_limit", "leverage_limit"),
    )

    net_debt = None
    if debt_balance is not None and cash_balance is not None:
        net_debt = debt_balance - cash_balance

    used_manual_keys = tuple(
        dict.fromkeys(
            [
                *(record.input_key for record in budget_inputs if revenue_plan is not None or ebitda_plan is not None or operating_cost_plan is not None),
                *(record.input_key for record in board_floor_inputs if board_floor is not None),
                *(record.input_key for record in covenant_inputs if covenant_limit is not None),
            ]
        )
    )

    return OracleKpiComputation(
        reporting_period_key=reporting_period_key,
        reporting_cadence=resolved_cadence,
        period_start=period_start,
        period_end=period_end,
        period_days=period_days,
        metrics={
            "revenue_attainment_pct": _safe_percent(revenue, revenue_plan),
            "ebitda_margin_pct": _safe_percent(ebitda, revenue),
            "ebitda_attainment_pct": _safe_percent(ebitda, ebitda_plan),
            "operating_cost_pct_of_plan": _safe_percent(operating_cost, operating_cost_plan),
            "cash_vs_board_floor_pct": _safe_percent(cash_balance, board_floor),
            "cash_floor_headroom": _safe_difference(cash_balance, board_floor),
            "dso_days": _days_metric(receivables, revenue, period_days),
            "dpo_days": _days_metric(payables, operating_cost, period_days),
            "dio_days": _days_metric(inventory, operating_cost, period_days),
            "ccc_days": _cash_conversion_cycle(
                _days_metric(receivables, revenue, period_days),
                _days_metric(inventory, operating_cost, period_days),
                _days_metric(payables, operating_cost, period_days),
            ),
            "net_debt_to_ebitda": _safe_ratio(net_debt, ebitda),
            "covenant_headroom": _safe_difference(covenant_limit, _safe_ratio(net_debt, ebitda)),
        },
        components={
            "revenue_actual": revenue,
            "revenue_plan": revenue_plan,
            "ebitda_actual": ebitda,
            "ebitda_plan": ebitda_plan,
            "operating_cost_actual": operating_cost,
            "operating_cost_plan": operating_cost_plan,
            "cash_balance": cash_balance,
            "board_floor": board_floor,
            "accounts_receivable_balance": receivables,
            "accounts_payable_balance": payables,
            "inventory_balance": inventory,
            "debt_balance": debt_balance,
            "net_debt": net_debt,
            "covenant_max_leverage": covenant_limit,
        },
        source_fact_types={
            "revenue": ("revenue",),
            "ebitda": ("ebitda",),
            "operating_cost": ("operating_cost", "opex", "operating_expense"),
            "cash_balance": ("cash_balance",),
            "accounts_receivable": ("accounts_receivable_balance", "ar_open_balance", "receivables_balance"),
            "accounts_payable": ("accounts_payable_balance", "ap_open_balance", "payables_balance"),
            "inventory": ("inventory_balance", "working_capital_inventory", "inventory_on_hand"),
            "debt": ("debt_balance", "borrowings", "loan_balance"),
        },
        manual_input_keys=used_manual_keys,
    )


def build_oracle_kpi_narration_payload(
    computation: OracleKpiComputation,
    *,
    commentary_inputs: Sequence[ManualInputRecord] | None = None,
) -> dict[str, Any]:
    return {
        "authoritative": False,
        "derived_from": "deterministic_oracle_kpi_engine",
        "reporting_period_key": computation.reporting_period_key,
        "reporting_cadence": computation.reporting_cadence,
        "period_days": computation.period_days,
        "metric_values": {
            key: _stringify_decimal(value) for key, value in computation.metrics.items()
        },
        "component_values": {
            key: _stringify_decimal(value) for key, value in computation.components.items()
        },
        "manual_input_keys": list(computation.manual_input_keys),
        "commentary_inputs": [
            {
                "input_key": record.input_key,
                "input_name": record.input_name,
                "period_key": record.period_key,
                "attributes": dict(record.attributes),
            }
            for record in (commentary_inputs or ())
        ],
        "instructions": "Narrative must treat metric_values and component_values as fixed computed numbers.",
    }


def compute_oracle_pilot_leakage(
    snapshot: OracleCanonicalSnapshot,
    *,
    reporting_period_key: str,
    reporting_cadence: Cadence | None = None,
) -> OracleLeakageReview:
    period_lookup = {period.period_key: period for period in snapshot.periods}
    period = period_lookup.get(reporting_period_key)
    resolved_cadence = reporting_cadence or (period.cadence if period else _infer_cadence_from_period_key(reporting_period_key))
    period_start, period_end = _resolve_period_bounds(
        reporting_period_key,
        resolved_cadence,
        period_start=period.period_start if period else None,
        period_end=period.period_end if period else None,
    )

    contract_inputs = _matching_manual_inputs(
        snapshot.manual_inputs,
        input_type="contract_registry",
        reporting_period_key=reporting_period_key,
        reporting_cadence=resolved_cadence,
        period_start=period_start,
        period_end=period_end,
    )
    hedge_inputs = _matching_manual_inputs(
        snapshot.manual_inputs,
        input_type="hedge_register",
        reporting_period_key=reporting_period_key,
        reporting_cadence=resolved_cadence,
        period_start=period_start,
        period_end=period_end,
    )
    contract_entries = _manual_collection_entries(contract_inputs, ("contracts", "line_items", "registry", "renewals"))
    hedge_entries = _manual_collection_entries(hedge_inputs, ("hedges", "line_items", "positions"))
    scoped_facts = [
        fact
        for fact in snapshot.facts
        if _window_overlaps(_fact_window(snapshot, fact), (period_start, period_end))
    ]

    findings = [
        *_detect_duplicate_payments(scoped_facts),
        *_detect_entity_resolution_duplicates(scoped_facts),
        *_detect_off_contract_spend(scoped_facts, contract_entries, period_end),
        *_detect_price_variance(scoped_facts, contract_entries),
        *_detect_missed_early_pay_discount(scoped_facts),
        *_detect_auto_renewal_escalation(contract_entries, period_start, period_end),
        *_detect_fx_hedge_not_applied(scoped_facts, hedge_entries, snapshot.metadata.get("reporting_currency") or "SAR"),
        *_detect_dormant_credit_balance(scoped_facts, period_end),
    ]
    findings.sort(
        key=lambda finding: (
            finding.recoverable_sar,
            finding.leakage_sar,
            finding.vendor_name.lower(),
            finding.finding_id,
        ),
        reverse=True,
    )
    ranked = tuple(
        replace(finding, priority_rank=index)
        for index, finding in enumerate(findings, start=1)
    )
    total_recoverable = sum((finding.recoverable_sar for finding in ranked), Decimal("0"))
    return OracleLeakageReview(
        reporting_period_key=reporting_period_key,
        reporting_cadence=resolved_cadence,
        period_start=period_start,
        period_end=period_end,
        findings=ranked,
        ranking_basis="recoverable_sar_desc",
        total_recoverable_sar=total_recoverable,
    )


def build_oracle_leakage_review_payload(review: OracleLeakageReview) -> dict[str, Any]:
    return {
        "authoritative": review.authoritative,
        "derived_from": "deterministic_oracle_leakage_engine",
        "reporting_period_key": review.reporting_period_key,
        "reporting_cadence": review.reporting_cadence,
        "period_start": review.period_start.isoformat(),
        "period_end": review.period_end.isoformat(),
        "ranking_basis": review.ranking_basis,
        "total_findings": len(review.findings),
        "total_recoverable_sar": _stringify_decimal(review.total_recoverable_sar),
        "computation_boundary": review.computation_boundary,
        "reviewer_workflow": {
            "order_by": "recoverable_sar_desc",
            "required_checks": [
                "Verify each evidence locator against the cited source row or manual input record.",
                "Challenge the quantity, rate, and date assumptions before approving recoverable value.",
                "Record approve or reject decision without changing deterministic calculation inputs silently.",
            ],
            "auditor_fields": [
                "finding_id",
                "pattern_type",
                "vendor_id",
                "recoverable_sar",
                "calculation",
                "evidence",
                "challenge_points",
            ],
        },
        "findings": [
            {
                "finding_id": finding.finding_id,
                "priority_rank": finding.priority_rank,
                "pattern_type": finding.pattern_type,
                "title": finding.title,
                "vendor_id": finding.vendor_id,
                "vendor_name": finding.vendor_name,
                "leakage_sar": _stringify_decimal(finding.leakage_sar),
                "recoverable_sar": _stringify_decimal(finding.recoverable_sar),
                "confidence": finding.confidence,
                "rationale": finding.rationale,
                "review_status": finding.review_status,
                "calculation": _stringify_nested_decimals(finding.calculation),
                "challenge_points": list(finding.challenge_points),
                "evidence": [
                    {
                        "source_kind": item.source_kind,
                        "source_key": item.source_key,
                        "locator": item.locator,
                        "details": _stringify_nested_decimals(item.details),
                    }
                    for item in finding.evidence
                ],
            }
            for finding in review.findings
        ],
    }


def _detect_duplicate_payments(facts: Sequence[CanonicalFinanceFact]) -> list[OracleLeakageFinding]:
    groups: dict[tuple[str, str, Decimal, str], list[CanonicalFinanceFact]] = defaultdict(list)
    for fact in facts:
        if fact.module != "AP":
            continue
        record = _fact_record(fact)
        invoice_number = _normalized_token(record.get("invoice_num") or record.get("invoice_reference"))
        payment_date = _date(record.get("payment_date"))
        payment_amount = _decimal(record.get("payment_amount") or record.get("amount_paid") or record.get("amount"))
        currency = str(record.get("currency") or fact.currency or "SAR").upper()
        if not invoice_number or payment_date is None or payment_amount in (None, Decimal("0")):
            continue
        vendor_id = _normalized_token(record.get("vendor_id")) or _normalized_token(record.get("vendor_name")) or "unknown"
        groups[(vendor_id, invoice_number, payment_amount, currency)].append(fact)

    findings: list[OracleLeakageFinding] = []
    for _, matched_facts in groups.items():
        if len(matched_facts) < 2:
            continue
        amounts = [_decimal(_fact_record(fact).get("payment_amount") or fact.amount_value) or Decimal("0") for fact in matched_facts]
        duplicate_value = sum(amounts, Decimal("0")) - max(amounts)
        if duplicate_value <= Decimal("0"):
            continue
        reference = _fact_record(matched_facts[0])
        vendor_id = str(reference.get("vendor_id") or reference.get("supplier_key") or "unknown")
        vendor_name = str(reference.get("vendor_name") or "Unknown vendor")
        invoice_number = str(reference.get("invoice_num") or reference.get("invoice_reference") or matched_facts[0].natural_key)
        findings.append(
            _make_finding(
                finding_id=f"duplicate-payment:{vendor_id}:{invoice_number}",
                title=f"Duplicate payment detected for invoice {invoice_number}",
                pattern_type="duplicate_payment",
                vendor_id=vendor_id,
                vendor_name=vendor_name,
                leakage_sar=duplicate_value,
                recoverable_sar=duplicate_value,
                confidence="high",
                rationale="Multiple AP payment legs share the same canonical vendor, invoice number, amount, and currency.",
                calculation={
                    "duplicate_count": len(matched_facts),
                    "payment_amounts": amounts,
                    "recoverable_formula": "sum(payment_amounts) - max(payment_amounts)",
                },
                evidence=[
                    _fact_evidence(
                        fact,
                        fields=("invoice_num", "payment_reference", "payment_date", "payment_amount", "vendor_id", "vendor_name"),
                    )
                    for fact in matched_facts
                ],
                challenge_points=(
                    "Confirm the duplicate legs are not a reversal and reissue pair.",
                    "Confirm all cited payment references cleared cash independently.",
                ),
            )
        )
    return findings


def _detect_entity_resolution_duplicates(facts: Sequence[CanonicalFinanceFact]) -> list[OracleLeakageFinding]:
    groups: dict[tuple[str, str, Decimal, str], list[CanonicalFinanceFact]] = defaultdict(list)
    for fact in facts:
        if fact.module != "AP":
            continue
        record = _fact_record(fact)
        invoice_number = _normalized_token(record.get("invoice_num") or record.get("invoice_reference"))
        payment_amount = _decimal(record.get("payment_amount") or record.get("amount_paid") or record.get("amount"))
        shared_key = _shared_entity_key(record)
        currency = str(record.get("currency") or fact.currency or "SAR").upper()
        if not invoice_number or payment_amount in (None, Decimal("0")) or shared_key is None:
            continue
        groups[(shared_key, invoice_number, payment_amount, currency)].append(fact)

    findings: list[OracleLeakageFinding] = []
    for (shared_key, _, _, _), matched_facts in groups.items():
        vendor_ids = {str(_fact_record(fact).get("vendor_id") or "unknown") for fact in matched_facts}
        if len(matched_facts) < 2 or len(vendor_ids) < 2:
            continue
        amounts = [_decimal(_fact_record(fact).get("payment_amount") or fact.amount_value) or Decimal("0") for fact in matched_facts]
        duplicate_value = sum(amounts, Decimal("0")) - max(amounts)
        if duplicate_value <= Decimal("0"):
            continue
        reference = _fact_record(matched_facts[0])
        findings.append(
            _make_finding(
                finding_id=f"entity-duplicate:{shared_key}:{reference.get('invoice_num') or matched_facts[0].natural_key}",
                title=f"Entity-resolution duplicate across vendor IDs for invoice {reference.get('invoice_num') or matched_facts[0].natural_key}",
                pattern_type="entity_resolution_duplicate",
                vendor_id="|".join(sorted(vendor_ids)),
                vendor_name=str(reference.get("vendor_name") or "Resolved supplier entity"),
                leakage_sar=duplicate_value,
                recoverable_sar=duplicate_value,
                confidence="high",
                rationale="The same invoice amount was paid to multiple vendor IDs that share a strong deterministic entity identifier.",
                calculation={
                    "shared_identifier": shared_key,
                    "vendor_ids": sorted(vendor_ids),
                    "payment_amounts": amounts,
                    "recoverable_formula": "sum(payment_amounts) - max(payment_amounts)",
                },
                evidence=[
                    _fact_evidence(
                        fact,
                        fields=(
                            "invoice_num",
                            "payment_reference",
                            "payment_amount",
                            "vendor_id",
                            "vendor_name",
                            "vendor_tax_id",
                            "iban",
                            "bank_account_number",
                        ),
                    )
                    for fact in matched_facts
                ],
                challenge_points=(
                    "Verify the shared identifier truly belongs to the same supplier entity.",
                    "Verify one leg is not an approved intercompany or legal-entity split payment.",
                ),
            )
        )
    return findings


def _detect_off_contract_spend(
    facts: Sequence[CanonicalFinanceFact],
    contract_entries: Sequence[dict[str, Any]],
    period_end: date,
) -> list[OracleLeakageFinding]:
    findings: list[OracleLeakageFinding] = []
    for fact in facts:
        if fact.module != "AP":
            continue
        record = _fact_record(fact)
        invoice_amount = _decimal(record.get("invoice_amount") or record.get("amount") or fact.amount_value)
        invoice_date = _date(record.get("invoice_date") or record.get("event_date")) or period_end
        vendor_id = str(record.get("vendor_id") or record.get("supplier_key") or "unknown")
        vendor_name = str(record.get("vendor_name") or "Unknown vendor")
        category = _normalized_token(record.get("category") or record.get("spend_category") or record.get("commodity_code"))
        invoice_number = _normalized_token(record.get("invoice_num") or record.get("invoice_reference"))
        if invoice_amount in (None, Decimal("0")) or invoice_number is None:
            continue
        candidate_contracts = [
            entry
            for entry in contract_entries
            if _contract_matches(entry, record, invoice_date)
        ]
        if not candidate_contracts and not bool(record.get("off_contract_flag")):
            continue
        if any(_normalized_token(entry.get("contract_id")) == _normalized_token(record.get("contract_id")) for entry in candidate_contracts if record.get("contract_id")):
            continue
        benchmark = _off_contract_benchmark(invoice_amount, record, candidate_contracts)
        if benchmark is None or benchmark >= invoice_amount:
            continue
        recoverable = invoice_amount - benchmark
        reference_contract = candidate_contracts[0] if candidate_contracts else None
        evidence: list[OracleLeakageEvidence] = [
            _fact_evidence(fact, fields=("invoice_num", "invoice_amount", "invoice_date", "category", "contract_id", "po_reference"))
        ]
        if reference_contract is not None:
            evidence.append(_manual_evidence(reference_contract, fields=("contract_id", "vendor_id", "category", "unit_price", "off_contract_savings_pct")))
        findings.append(
            _make_finding(
                finding_id=f"off-contract:{vendor_id}:{record.get('invoice_num') or fact.natural_key}",
                title=f"Off-contract spend detected for {record.get('invoice_num') or fact.natural_key}",
                pattern_type="off_contract_spend",
                vendor_id=vendor_id,
                vendor_name=vendor_name,
                leakage_sar=invoice_amount,
                recoverable_sar=recoverable,
                confidence="high",
                rationale="AP spend landed outside a matched active contract or approved contract reference.",
                calculation={
                    "invoice_amount": invoice_amount,
                    "benchmark_amount": benchmark,
                    "recoverable_formula": "invoice_amount - benchmark_amount",
                    "category": category,
                },
                evidence=evidence,
                challenge_points=(
                    "Confirm the contract registry was complete for the invoice date and category.",
                    "Confirm the invoice was not intentionally exempt from contract routing.",
                ),
            )
        )
    return findings


def _detect_price_variance(
    facts: Sequence[CanonicalFinanceFact],
    contract_entries: Sequence[dict[str, Any]],
) -> list[OracleLeakageFinding]:
    po_lookup: dict[str, CanonicalFinanceFact] = {}
    for fact in facts:
        if fact.module != "PO":
            continue
        record = _fact_record(fact)
        po_key = _normalized_token(record.get("po_reference") or record.get("po_line_id") or fact.source_reference or fact.natural_key)
        if po_key:
            po_lookup[po_key] = fact
    findings: list[OracleLeakageFinding] = []
    for fact in facts:
        if fact.module != "AP":
            continue
        record = _fact_record(fact)
        quantity = _decimal(record.get("quantity") or record.get("qty"))
        invoice_unit_price = _decimal(record.get("invoice_unit_price") or record.get("unit_price"))
        if quantity in (None, Decimal("0")) or invoice_unit_price is None:
            continue
        po_reference = _normalized_token(record.get("po_reference"))
        po_fact = po_lookup.get(po_reference or "")
        po_unit_price = _decimal(_fact_record(po_fact).get("po_unit_price") or _fact_record(po_fact).get("unit_price")) if po_fact else None
        invoice_date = _date(record.get("invoice_date") or record.get("event_date"))
        matching_contracts = [entry for entry in contract_entries if _contract_matches(entry, record, invoice_date)]
        contract_unit_price = _first_decimal(matching_contracts, "unit_price", "contract_unit_price", "approved_unit_price")
        baseline_unit_price = contract_unit_price if contract_unit_price is not None else po_unit_price
        if baseline_unit_price is None or invoice_unit_price <= baseline_unit_price:
            continue
        recoverable = (invoice_unit_price - baseline_unit_price) * quantity
        evidence: list[OracleLeakageEvidence] = [
            _fact_evidence(fact, fields=("invoice_num", "po_reference", "quantity", "invoice_unit_price", "unit_price"))
        ]
        if po_fact is not None:
            evidence.append(_fact_evidence(po_fact, fields=("po_reference", "po_unit_price", "unit_price", "quantity")))
        if matching_contracts:
            evidence.append(_manual_evidence(matching_contracts[0], fields=("contract_id", "unit_price", "approved_unit_price")))
        findings.append(
            _make_finding(
                finding_id=f"price-variance:{record.get('vendor_id') or 'unknown'}:{record.get('invoice_num') or fact.natural_key}",
                title=f"Price variance detected for {record.get('invoice_num') or fact.natural_key}",
                pattern_type="price_variance",
                vendor_id=str(record.get("vendor_id") or "unknown"),
                vendor_name=str(record.get("vendor_name") or "Unknown vendor"),
                leakage_sar=recoverable,
                recoverable_sar=recoverable,
                confidence="high",
                rationale="The invoiced unit price exceeded the deterministic PO or contract baseline.",
                calculation={
                    "quantity": quantity,
                    "invoice_unit_price": invoice_unit_price,
                    "baseline_unit_price": baseline_unit_price,
                    "recoverable_formula": "(invoice_unit_price - baseline_unit_price) * quantity",
                },
                evidence=evidence,
                challenge_points=(
                    "Confirm quantity matches the billed unit of measure.",
                    "Confirm the cited PO or contract baseline was still valid on the invoice date.",
                ),
            )
        )
    return findings


def _detect_missed_early_pay_discount(facts: Sequence[CanonicalFinanceFact]) -> list[OracleLeakageFinding]:
    findings: list[OracleLeakageFinding] = []
    for fact in facts:
        if fact.module != "AP":
            continue
        record = _fact_record(fact)
        invoice_amount = _decimal(record.get("invoice_amount") or record.get("amount") or fact.amount_value)
        payment_date = _date(record.get("payment_date"))
        discount_due_date = _date(record.get("discount_due_date"))
        if invoice_amount is None or payment_date is None or discount_due_date is None or payment_date <= discount_due_date:
            continue
        discount_amount = _decimal(record.get("discount_amount"))
        if discount_amount is None:
            discount_pct = _decimal(record.get("discount_pct") or record.get("early_pay_discount_pct"))
            if discount_pct is None:
                continue
            discount_amount = invoice_amount * (discount_pct / Decimal("100"))
        if discount_amount <= Decimal("0"):
            continue
        findings.append(
            _make_finding(
                finding_id=f"missed-discount:{record.get('vendor_id') or 'unknown'}:{record.get('invoice_num') or fact.natural_key}",
                title=f"Missed early-pay discount on {record.get('invoice_num') or fact.natural_key}",
                pattern_type="missed_early_pay_discount",
                vendor_id=str(record.get("vendor_id") or "unknown"),
                vendor_name=str(record.get("vendor_name") or "Unknown vendor"),
                leakage_sar=discount_amount,
                recoverable_sar=discount_amount,
                confidence="high",
                rationale="Payment cleared after the deterministic discount window despite an available early-pay discount.",
                calculation={
                    "invoice_amount": invoice_amount,
                    "payment_date": payment_date.isoformat(),
                    "discount_due_date": discount_due_date.isoformat(),
                    "discount_amount": discount_amount,
                },
                evidence=[
                    _fact_evidence(
                        fact,
                        fields=("invoice_num", "invoice_amount", "payment_date", "discount_due_date", "discount_pct", "discount_amount"),
                    )
                ],
                challenge_points=(
                    "Confirm the supplier discount terms were active for this invoice.",
                    "Confirm the payment timing was not contractually constrained by a dispute or hold.",
                ),
            )
        )
    return findings


def _detect_auto_renewal_escalation(
    contract_entries: Sequence[dict[str, Any]],
    period_start: date,
    period_end: date,
) -> list[OracleLeakageFinding]:
    findings: list[OracleLeakageFinding] = []
    for entry in contract_entries:
        if not bool(entry.get("auto_renewal")):
            continue
        renewal_date = _date(entry.get("renewal_date") or entry.get("renewed_start_date") or entry.get("effective_date"))
        if renewal_date is None or not (period_start <= renewal_date <= period_end):
            continue
        previous_value = _decimal(entry.get("previous_annual_value") or entry.get("previous_value"))
        renewed_value = _decimal(entry.get("renewed_annual_value") or entry.get("renewed_value"))
        previous_unit_price = _decimal(entry.get("previous_unit_price"))
        renewed_unit_price = _decimal(entry.get("renewed_unit_price") or entry.get("unit_price"))
        renewal_quantity = _decimal(entry.get("renewal_quantity") or entry.get("quantity") or Decimal("1")) or Decimal("1")
        recoverable: Decimal | None = None
        calculation: dict[str, Any]
        if previous_value is not None and renewed_value is not None and renewed_value > previous_value:
            recoverable = renewed_value - previous_value
            calculation = {
                "previous_annual_value": previous_value,
                "renewed_annual_value": renewed_value,
                "recoverable_formula": "renewed_annual_value - previous_annual_value",
            }
        elif previous_unit_price is not None and renewed_unit_price is not None and renewed_unit_price > previous_unit_price:
            recoverable = (renewed_unit_price - previous_unit_price) * renewal_quantity
            calculation = {
                "previous_unit_price": previous_unit_price,
                "renewed_unit_price": renewed_unit_price,
                "renewal_quantity": renewal_quantity,
                "recoverable_formula": "(renewed_unit_price - previous_unit_price) * renewal_quantity",
            }
        else:
            continue
        findings.append(
            _make_finding(
                finding_id=f"auto-renewal:{entry.get('vendor_id') or entry.get('vendor_name') or 'unknown'}:{entry.get('contract_id') or entry.get('__item_index')}",
                title=f"Auto-renewal escalation on contract {entry.get('contract_id') or 'unknown'}",
                pattern_type="auto_renewal_escalation",
                vendor_id=str(entry.get("vendor_id") or "unknown"),
                vendor_name=str(entry.get("vendor_name") or "Unknown vendor"),
                leakage_sar=recoverable,
                recoverable_sar=recoverable,
                confidence="high",
                rationale="The contract auto-renewed in-period at a higher deterministic rate or annual value.",
                calculation=calculation | {"renewal_date": renewal_date.isoformat()},
                evidence=[_manual_evidence(entry, fields=("contract_id", "renewal_date", "previous_annual_value", "renewed_annual_value", "previous_unit_price", "renewed_unit_price"))],
                challenge_points=(
                    "Confirm the renewal increase was not explicitly approved outside the registry baseline.",
                    "Confirm the previous commercial baseline is the last negotiated value, not a temporary discount.",
                ),
            )
        )
    return findings


def _detect_fx_hedge_not_applied(
    facts: Sequence[CanonicalFinanceFact],
    hedge_entries: Sequence[dict[str, Any]],
    reporting_currency: str,
) -> list[OracleLeakageFinding]:
    findings: list[OracleLeakageFinding] = []
    normalized_reporting = str(reporting_currency or "SAR").upper()
    for fact in facts:
        record = _fact_record(fact)
        currency = str(record.get("currency") or fact.currency or normalized_reporting).upper()
        if currency == normalized_reporting:
            continue
        foreign_amount = _decimal(record.get("foreign_amount") or record.get("amount_foreign") or record.get("quantity_foreign"))
        applied_fx_rate = _decimal(record.get("applied_fx_rate") or record.get("spot_rate") or record.get("fx_rate"))
        if foreign_amount in (None, Decimal("0")) or applied_fx_rate is None:
            continue
        matching_hedges = [entry for entry in hedge_entries if _hedge_matches(entry, record, currency)]
        hedge_rate = _first_decimal(matching_hedges, "hedged_rate", "contracted_rate", "rate")
        if hedge_rate is None or applied_fx_rate <= hedge_rate:
            continue
        recoverable = (applied_fx_rate - hedge_rate) * foreign_amount
        evidence: list[OracleLeakageEvidence] = [
            _fact_evidence(fact, fields=("invoice_num", "vendor_id", "currency", "foreign_amount", "applied_fx_rate", "spot_rate"))
        ]
        if matching_hedges:
            evidence.append(_manual_evidence(matching_hedges[0], fields=("hedge_id", "currency", "hedged_rate", "vendor_id", "invoice_num")))
        findings.append(
            _make_finding(
                finding_id=f"fx-hedge:{record.get('vendor_id') or 'unknown'}:{record.get('invoice_num') or fact.natural_key}",
                title=f"FX hedge not applied for {record.get('invoice_num') or fact.natural_key}",
                pattern_type="fx_hedge_not_applied",
                vendor_id=str(record.get("vendor_id") or "unknown"),
                vendor_name=str(record.get("vendor_name") or "Unknown vendor"),
                leakage_sar=recoverable,
                recoverable_sar=recoverable,
                confidence="high",
                rationale="A registered hedge rate existed, but the AP transaction settled at a worse deterministic FX rate.",
                calculation={
                    "foreign_amount": foreign_amount,
                    "applied_fx_rate": applied_fx_rate,
                    "hedged_rate": hedge_rate,
                    "recoverable_formula": "(applied_fx_rate - hedged_rate) * foreign_amount",
                },
                evidence=evidence,
                challenge_points=(
                    "Confirm the hedge covered this invoice, currency, and settlement window.",
                    "Confirm the applied rate already includes no approved fees or taxes outside hedge scope.",
                ),
            )
        )
    return findings


def _detect_dormant_credit_balance(
    facts: Sequence[CanonicalFinanceFact],
    period_end: date,
) -> list[OracleLeakageFinding]:
    findings: list[OracleLeakageFinding] = []
    for fact in facts:
        if fact.module != "AP":
            continue
        record = _fact_record(fact)
        credit_balance = _decimal(record.get("credit_balance_amount") or record.get("credit_amount"))
        if credit_balance is None and fact.fact_type.lower() in {"credit_balance", "credit_note", "vendor_credit"}:
            base_amount = _decimal(record.get("amount") or fact.amount_value)
            if base_amount is not None:
                credit_balance = abs(base_amount)
        if credit_balance is None or credit_balance <= Decimal("0"):
            continue
        last_activity = _date(record.get("last_activity_date") or record.get("credit_date") or record.get("invoice_date"))
        dormant_days = int(record.get("dormant_threshold_days") or 90)
        if last_activity is None or (period_end - last_activity).days < dormant_days:
            continue
        if str(record.get("credit_status") or "open").lower() not in {"open", "unapplied", "available", "dormant"}:
            continue
        findings.append(
            _make_finding(
                finding_id=f"dormant-credit:{record.get('vendor_id') or 'unknown'}:{record.get('credit_reference') or fact.natural_key}",
                title=f"Dormant credit balance for {record.get('credit_reference') or fact.natural_key}",
                pattern_type="dormant_credit_balance",
                vendor_id=str(record.get("vendor_id") or "unknown"),
                vendor_name=str(record.get("vendor_name") or "Unknown vendor"),
                leakage_sar=credit_balance,
                recoverable_sar=credit_balance,
                confidence="high",
                rationale="Supplier credit remained unapplied beyond the deterministic dormancy threshold.",
                calculation={
                    "credit_balance_amount": credit_balance,
                    "last_activity_date": last_activity.isoformat(),
                    "dormant_days": (period_end - last_activity).days,
                    "dormant_threshold_days": dormant_days,
                },
                evidence=[_fact_evidence(fact, fields=("credit_reference", "credit_balance_amount", "last_activity_date", "credit_status"))],
                challenge_points=(
                    "Confirm the credit has not already been earmarked against a future invoice.",
                    "Confirm the vendor statement still shows the credit as open and collectible.",
                ),
            )
        )
    return findings


def _fact_record(fact: CanonicalFinanceFact | None) -> dict[str, Any]:
    if fact is None:
        return {}
    record = dict(fact.attributes)
    record.setdefault("natural_key", fact.natural_key)
    record.setdefault("module", fact.module)
    record.setdefault("fact_type", fact.fact_type)
    record.setdefault("amount", fact.amount_value)
    record.setdefault("currency", fact.currency)
    record.setdefault("period_key", fact.period_key)
    record.setdefault("source_reference", fact.source_reference)
    return record


def _manual_collection_entries(
    records: Sequence[ManualInputRecord],
    collection_keys: Sequence[str],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for record in records:
        containers: list[Sequence[Any]] = []
        for key in collection_keys:
            candidate = record.attributes.get(key)
            if isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes)):
                containers.append(candidate)
        if not containers and isinstance(record.attributes.get("line_items"), Sequence) and not isinstance(record.attributes.get("line_items"), (str, bytes)):
            containers.append(record.attributes["line_items"])
        if not containers:
            containers.append((record.attributes,))
        for collection in containers:
            for index, item in enumerate(collection, start=1):
                if not isinstance(item, Mapping):
                    continue
                entry = dict(item)
                entry.setdefault("__input_key", record.input_key)
                entry.setdefault("__input_name", record.input_name)
                entry.setdefault("__item_index", index)
                entries.append(entry)
    return entries


def _contract_matches(entry: Mapping[str, Any], record: Mapping[str, Any], invoice_date: date | None) -> bool:
    entry_vendor = _normalized_token(entry.get("vendor_id") or entry.get("canonical_vendor_key") or entry.get("vendor_tax_id") or entry.get("vendor_name"))
    record_vendor = _normalized_token(record.get("vendor_id") or record.get("vendor_tax_id") or record.get("vendor_name"))
    entry_category = _normalized_token(entry.get("category") or entry.get("spend_category") or entry.get("commodity_code"))
    record_category = _normalized_token(record.get("category") or record.get("spend_category") or record.get("commodity_code"))
    if entry_vendor and record_vendor and entry_vendor != record_vendor:
        return False
    if entry_category and record_category and entry_category != record_category:
        return False
    start = _date(entry.get("start_date") or entry.get("effective_date"))
    end = _date(entry.get("end_date") or entry.get("expiry_date"))
    if invoice_date is not None and start is not None and invoice_date < start:
        return False
    if invoice_date is not None and end is not None and invoice_date > end:
        return False
    return True


def _off_contract_benchmark(
    invoice_amount: Decimal,
    record: Mapping[str, Any],
    contracts: Sequence[Mapping[str, Any]],
) -> Decimal | None:
    quantity = _decimal(record.get("quantity") or record.get("qty"))
    contract_unit_price = _first_decimal(contracts, "unit_price", "contract_unit_price", "approved_unit_price")
    if quantity not in (None, Decimal("0")) and contract_unit_price is not None:
        return contract_unit_price * quantity
    savings_pct = _first_decimal(contracts, "off_contract_savings_pct", "negotiated_discount_pct")
    if savings_pct is None:
        return None
    return invoice_amount * (Decimal("1") - (savings_pct / Decimal("100")))


def _hedge_matches(entry: Mapping[str, Any], record: Mapping[str, Any], currency: str) -> bool:
    if str(entry.get("currency") or "").upper() not in {"", currency.upper()}:
        return False
    entry_vendor = _normalized_token(entry.get("vendor_id") or entry.get("vendor_name"))
    record_vendor = _normalized_token(record.get("vendor_id") or record.get("vendor_name"))
    if entry_vendor and record_vendor and entry_vendor != record_vendor:
        return False
    entry_invoice = _normalized_token(entry.get("invoice_num") or entry.get("invoice_reference"))
    record_invoice = _normalized_token(record.get("invoice_num") or record.get("invoice_reference"))
    if entry_invoice and record_invoice and entry_invoice != record_invoice:
        return False
    return True


def _vendor_canonical_key(record: Mapping[str, Any]) -> str:
    return (
        _shared_entity_key(record)
        or _normalized_token(record.get("vendor_id"))
        or _normalized_token(record.get("vendor_name"))
        or "unknown"
    )


def _shared_entity_key(record: Mapping[str, Any]) -> str | None:
    for key in ("vendor_tax_id", "tax_id", "vat_number", "iban", "bank_account_number", "bank_account", "swift_code"):
        normalized = _normalized_token(record.get(key))
        if normalized:
            return f"{key}:{normalized}"
    return None


def _normalized_token(value: Any) -> str | None:
    text = _text(value)
    if text is None:
        return None
    compact = "".join(character for character in text.upper() if character.isalnum())
    return compact or None


def _first_decimal(records: Sequence[Mapping[str, Any]], *keys: str) -> Decimal | None:
    for record in records:
        for key in keys:
            value = _decimal(record.get(key))
            if value is not None:
                return value
    return None


def _fact_evidence(fact: CanonicalFinanceFact, *, fields: Sequence[str]) -> OracleLeakageEvidence:
    record = _fact_record(fact)
    return OracleLeakageEvidence(
        source_kind="fact",
        source_key=fact.natural_key,
        locator=f"{fact.module}:{fact.fact_type}",
        details={field: record.get(field) for field in fields if field in record},
    )


def _manual_evidence(entry: Mapping[str, Any], *, fields: Sequence[str]) -> OracleLeakageEvidence:
    source_key = str(entry.get("__input_key") or "manual-input")
    item_index = entry.get("__item_index")
    locator = f"{source_key}#{item_index}" if item_index is not None else source_key
    return OracleLeakageEvidence(
        source_kind="manual_input",
        source_key=source_key,
        locator=locator,
        details={field: entry.get(field) for field in fields if field in entry},
    )


def _make_finding(
    *,
    finding_id: str,
    title: str,
    pattern_type: str,
    vendor_id: str,
    vendor_name: str,
    leakage_sar: Decimal,
    recoverable_sar: Decimal,
    confidence: Literal["high", "medium", "low"],
    rationale: str,
    calculation: dict[str, Any],
    evidence: Sequence[OracleLeakageEvidence],
    challenge_points: Sequence[str],
) -> OracleLeakageFinding:
    return OracleLeakageFinding(
        finding_id=finding_id,
        title=title,
        pattern_type=pattern_type,
        vendor_id=vendor_id,
        vendor_name=vendor_name,
        leakage_sar=leakage_sar,
        recoverable_sar=recoverable_sar,
        confidence=confidence,
        rationale=rationale,
        calculation=calculation,
        evidence=tuple(_unique_evidence(evidence)),
        challenge_points=tuple(challenge_points),
    )


def _unique_evidence(evidence: Sequence[OracleLeakageEvidence]) -> list[OracleLeakageEvidence]:
    unique: list[OracleLeakageEvidence] = []
    seen: set[tuple[str, str, str, tuple[tuple[str, str], ...]]] = set()
    for item in evidence:
        key = (
            item.source_kind,
            item.source_key,
            item.locator,
            tuple(sorted((str(name), str(value)) for name, value in item.details.items())),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _stringify_nested_decimals(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _stringify_decimal(value)
    if isinstance(value, dict):
        return {key: _stringify_nested_decimals(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_stringify_nested_decimals(item) for item in value]
    return value


def _map_fact(
    module: OracleModule,
    row: Mapping[str, Any],
    *,
    index: int,
    bu_mapping: BUFlexfieldMappingConfig,
    reporting_currency: str,
) -> CanonicalFinanceFact:
    cadence = str(row.get("cadence") or DEFAULT_CADENCE_BY_MODULE[module])
    natural_key = _text(row.get("natural_key")) or _text(row.get("reference")) or f"{module}:{index}"
    period_key = _derive_period_key(row, cadence)
    bu_code, resolved_cost_centre, segment_name = bu_mapping.resolve(
        row.get("flexfield_segments"),
        fallback_cost_centre=_text(row.get("cost_centre")),
    )
    amount_value = _decimal(row.get("amount"))
    attributes = dict(row)
    attributes.setdefault("bu_segment_name", segment_name)
    return CanonicalFinanceFact(
        natural_key=natural_key,
        module=module,
        fact_type=_fact_type_for(module, row),
        period_key=period_key,
        cadence=cadence,
        amount_value=amount_value,
        currency=_text(row.get("currency")) or reporting_currency,
        reporting_currency=reporting_currency,
        bu_code=bu_code,
        cost_centre=resolved_cost_centre,
        account_code=_text(row.get("account_code")),
        source_reference=_text(row.get("source_reference")) or _text(row.get("reference")),
        attributes=attributes,
    )


def _map_fx_rate(
    row: Mapping[str, Any],
    index: int,
    *,
    reporting_currency: str,
) -> FXRateRecord:
    rate_date = _date(row.get("rate_date")) or _date(row.get("as_of_date")) or date.today()
    source_currency = _text(row.get("source_currency")) or "USD"
    rate_source = _text(row.get("rate_source")) or "oracle_gl_daily_rates"
    rate_key = _text(row.get("rate_key")) or f"{source_currency}:{reporting_currency}:{rate_date.isoformat()}:{index}"
    rate_value = _decimal(row.get("rate_value")) or Decimal("0")
    return FXRateRecord(
        rate_key=rate_key,
        source_currency=source_currency,
        reporting_currency=_text(row.get("reporting_currency")) or reporting_currency,
        rate_source=rate_source,
        rate_date=rate_date,
        rate_value=rate_value,
        fallback_allowed=bool(row.get("fallback_allowed", False)),
        attributes=dict(row),
    )


def _period_from_row(
    row: Mapping[str, Any],
    *,
    period_key: str,
    cadence: Cadence,
) -> PeriodMetadata:
    raw_start = _date(row.get("period_start")) or _date(row.get("event_date")) or _date(row.get("as_of_date"))
    raw_end = _date(row.get("period_end"))
    start, end = _resolve_period_bounds(period_key, cadence, period_start=raw_start, period_end=raw_end)
    label = _text(row.get("period_name")) or period_key
    return PeriodMetadata(
        period_key=period_key,
        label=label,
        cadence=cadence,
        period_start=start,
        period_end=end,
        source_period_name=_text(row.get("period_name")),
        attributes={"module": row.get("module")},
    )


def _derive_period_key(row: Mapping[str, Any], cadence: Cadence) -> str:
    explicit = _text(row.get("period_key")) or _text(row.get("period_name"))
    if explicit:
        return explicit
    value = _date(row.get("event_date")) or _date(row.get("as_of_date")) or _date(row.get("period_start"))
    if value is None:
        return f"unspecified:{cadence}"
    if cadence == "daily":
        return value.isoformat()
    if cadence == "weekly":
        iso = value.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if cadence == "monthly":
        return f"{value.year}-{value.month:02d}"
    quarter = ((value.month - 1) // 3) + 1
    return f"{value.year}-Q{quarter}"


def _fact_type_for(module: OracleModule, row: Mapping[str, Any]) -> str:
    explicit = _text(row.get("fact_type"))
    if explicit:
        return explicit
    defaults: dict[OracleModule, str] = {
        "GL": "gl_balance",
        "AR": "ar_open_balance",
        "AP": "ap_open_balance",
        "CE": "cash_balance",
        "FA": "fixed_asset_balance",
        "PO": "purchase_commitment",
        "INV": "inventory_on_hand",
    }
    return defaults[module]


def _normalize_segments(value: Sequence[str] | str | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [segment.strip() for segment in value.split("-")]
    return [str(segment).strip() for segment in value]


def _date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _sum_metric_facts(
    snapshot: OracleCanonicalSnapshot,
    *,
    reporting_period_key: str,
    reporting_cadence: Cadence,
    period_start: date,
    period_end: date,
    fact_types: Sequence[str],
) -> Decimal | None:
    facts = _matching_facts(
        snapshot,
        reporting_period_key=reporting_period_key,
        reporting_cadence=reporting_cadence,
        period_start=period_start,
        period_end=period_end,
        fact_types=fact_types,
        prefer_exact_cadence=True,
    )
    amounts = [fact.amount_value for fact in facts if fact.amount_value is not None]
    if not amounts:
        return None
    return sum(amounts, Decimal("0"))


def _latest_metric_fact(
    snapshot: OracleCanonicalSnapshot,
    *,
    reporting_period_key: str,
    reporting_cadence: Cadence,
    period_start: date,
    period_end: date,
    fact_types: Sequence[str],
) -> Decimal | None:
    facts = _matching_facts(
        snapshot,
        reporting_period_key=reporting_period_key,
        reporting_cadence=reporting_cadence,
        period_start=period_start,
        period_end=period_end,
        fact_types=fact_types,
        prefer_exact_cadence=False,
    )
    if not facts:
        return None
    latest = max(
        facts,
        key=lambda fact: _fact_window(snapshot, fact)[1],
    )
    return latest.amount_value


def _matching_facts(
    snapshot: OracleCanonicalSnapshot,
    *,
    reporting_period_key: str,
    reporting_cadence: Cadence,
    period_start: date,
    period_end: date,
    fact_types: Sequence[str],
    prefer_exact_cadence: bool,
) -> list[CanonicalFinanceFact]:
    aliases = {alias.lower() for alias in fact_types}
    exact = [
        fact
        for fact in snapshot.facts
        if fact.fact_type.lower() in aliases
        and fact.period_key == reporting_period_key
        and fact.cadence == reporting_cadence
    ]
    if exact:
        return exact
    nested = [
        fact
        for fact in snapshot.facts
        if fact.fact_type.lower() in aliases
        and _window_within(_fact_window(snapshot, fact), (period_start, period_end))
    ]
    if prefer_exact_cadence:
        exact_cadence = [fact for fact in nested if fact.cadence == reporting_cadence]
        if exact_cadence:
            return exact_cadence
    return nested


def _fact_window(snapshot: OracleCanonicalSnapshot, fact: CanonicalFinanceFact) -> tuple[date, date]:
    period = next((item for item in snapshot.periods if item.period_key == fact.period_key and item.cadence == fact.cadence), None)
    return _resolve_period_bounds(
        fact.period_key,
        fact.cadence,
        period_start=period.period_start if period else None,
        period_end=period.period_end if period else None,
    )


def _matching_manual_inputs(
    manual_inputs: Sequence[ManualInputRecord],
    *,
    input_type: ManualInputType,
    reporting_period_key: str,
    reporting_cadence: Cadence,
    period_start: date,
    period_end: date,
) -> list[ManualInputRecord]:
    exact = [
        record
        for record in manual_inputs
        if record.input_type == input_type
        and record.period_key == reporting_period_key
        and record.cadence == reporting_cadence
    ]
    if exact:
        return exact
    return [
        record
        for record in manual_inputs
        if record.input_type == input_type
        and _window_overlaps(_manual_input_window(record), (period_start, period_end))
    ]


def _manual_input_window(record: ManualInputRecord) -> tuple[date, date]:
    if record.period_key:
        return _resolve_period_bounds(record.period_key, record.cadence)
    today = date.today()
    return today, today


def _manual_decimal(records: Sequence[ManualInputRecord], *, aliases: Sequence[str]) -> Decimal | None:
    normalized_aliases = {alias.lower() for alias in aliases}
    for record in records:
        containers = [record.attributes]
        for key in ("metrics", "values", "kpis", "terms"):
            candidate = record.attributes.get(key)
            if isinstance(candidate, Mapping):
                containers.append(candidate)
        for container in containers:
            for alias in normalized_aliases:
                for key, value in container.items():
                    if str(key).strip().lower() == alias:
                        decimal_value = _decimal(value)
                        if decimal_value is not None:
                            return decimal_value
        line_items = record.attributes.get("line_items")
        if isinstance(line_items, Sequence) and not isinstance(line_items, (str, bytes)):
            for item in line_items:
                if not isinstance(item, Mapping):
                    continue
                item_key = _text(item.get("metric") or item.get("key") or item.get("fact_type"))
                if item_key and item_key.lower() in normalized_aliases:
                    decimal_value = _decimal(item.get("value") or item.get("amount") or item.get("limit"))
                    if decimal_value is not None:
                        return decimal_value
    return None


def _safe_percent(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    ratio = _safe_ratio(numerator, denominator)
    if ratio is None:
        return None
    return ratio * Decimal("100")


def _safe_ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator in (None, Decimal("0")):
        return None
    return numerator / denominator


def _safe_difference(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None:
        return None
    return left - right


def _days_metric(balance: Decimal | None, denominator: Decimal | None, period_days: int) -> Decimal | None:
    ratio = _safe_ratio(balance, denominator)
    if ratio is None:
        return None
    return ratio * Decimal(period_days)


def _cash_conversion_cycle(
    dso_days: Decimal | None,
    dio_days: Decimal | None,
    dpo_days: Decimal | None,
) -> Decimal | None:
    if dso_days is None or dio_days is None or dpo_days is None:
        return None
    return dso_days + dio_days - dpo_days


def _window_within(candidate: tuple[date, date], target: tuple[date, date]) -> bool:
    return candidate[0] >= target[0] and candidate[1] <= target[1]


def _window_overlaps(candidate: tuple[date, date], target: tuple[date, date]) -> bool:
    return candidate[0] <= target[1] and candidate[1] >= target[0]


def _resolve_period_bounds(
    period_key: str,
    cadence: Cadence,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
) -> tuple[date, date]:
    if period_start and period_end:
        return period_start, period_end
    if cadence == "daily":
        resolved = period_start or _date(period_key) or date.today()
        return resolved, period_end or resolved
    if cadence == "weekly":
        year_str, week_str = period_key.split("-W", 1) if "-W" in period_key else (None, None)
        if year_str and week_str:
            start = date.fromisocalendar(int(year_str), int(week_str), 1)
        else:
            start = period_start or date.today()
        return start, period_end or (start + timedelta(days=6))
    if cadence == "monthly":
        if period_key and len(period_key) >= 7 and period_key[4] == "-":
            year = int(period_key[:4])
            month = int(period_key[5:7])
            start = period_start or date(year, month, 1)
            last_day = calendar.monthrange(year, month)[1]
            return start, period_end or date(year, month, last_day)
    if cadence == "quarterly" and "-Q" in period_key:
        year = int(period_key[:4])
        quarter = int(period_key.split("-Q", 1)[1])
        month = ((quarter - 1) * 3) + 1
        start = period_start or date(year, month, 1)
        end_month = month + 2
        last_day = calendar.monthrange(year, end_month)[1]
        return start, period_end or date(year, end_month, last_day)
    resolved = period_start or _date(period_key) or date.today()
    return resolved, period_end or resolved


def _infer_cadence_from_period_key(period_key: str) -> Cadence:
    if "-W" in period_key:
        return "weekly"
    if "-Q" in period_key:
        return "quarterly"
    if len(period_key) == 10 and period_key.count("-") == 2:
        return "daily"
    return "monthly"


def _stringify_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    normalized = format(value.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"
