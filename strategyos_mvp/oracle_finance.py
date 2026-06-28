from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
    start = _date(row.get("period_start")) or _date(row.get("event_date")) or _date(row.get("as_of_date"))
    end = _date(row.get("period_end"))
    if start and end is None:
        if cadence == "daily":
            end = start
        elif cadence == "weekly":
            end = start + timedelta(days=6)
        elif cadence == "monthly":
            end = start
        elif cadence == "quarterly":
            end = start
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
