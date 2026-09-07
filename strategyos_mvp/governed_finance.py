from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


COMPONENT_KEYS = frozenset(
    {
        "revenue_actual",
        "revenue_plan",
        "cogs_actual",
        "ebitda_actual",
        "ebitda_plan",
        "operating_cost_actual",
        "operating_cost_plan",
        "cash_balance",
        "board_floor",
    }
)

FINANCE_HEADLINE_METRIC_KEYS = frozenset(
    {
        "ceo.revenue",
        "ceo.cogs",
        "ceo.ebitda",
        "ceo.ebitda_margin",
        "ceo.operating_cost",
        "ceo.cash_balance",
        "ceo.cash_floor",
    }
)

FINANCE_PRESENTATION_METRIC_KEYS = frozenset(
    {
        "ceo.presentation.trend",
        "ceo.presentation.contributor",
        "ceo.presentation.cost_component",
    }
)

EVIDENCE_COMPONENTS: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue_actual", "revenue_plan"),
    "ebitda_margin": ("ebitda_actual", "ebitda_plan", "cogs_actual"),
    "operating_cost": ("operating_cost_actual", "operating_cost_plan"),
    "cash_vs_floor": ("cash_balance", "board_floor"),
}


COMPONENT_CONTRACTS = {
    "revenue_actual": ("ceo.revenue", "actual"),
    "revenue_plan": ("ceo.revenue", "plan"),
    "cogs_actual": ("ceo.cogs", "actual"),
    "ebitda_actual": ("ceo.ebitda", "actual"),
    "ebitda_plan": ("ceo.ebitda", "plan"),
    "operating_cost_actual": ("ceo.operating_cost", "actual"),
    "operating_cost_plan": ("ceo.operating_cost", "plan"),
    "cash_balance": ("ceo.cash_balance", "actual"),
    "board_floor": ("ceo.cash_floor", "plan"),
    "ebitda_margin_actual": ("ceo.ebitda_margin", "actual"),
    "ebitda_margin_plan": ("ceo.ebitda_margin", "plan"),
}


def _normalized_value(record: Mapping[str, Any]) -> str:
    try:
        value = Decimal(str(record.get("value")))
        scale = Decimal(str(record.get("scale")))
        if not value.is_finite() or not scale.is_finite() or scale <= 0:
            raise ValueError("Non-finite value or invalid scale")
        normalized = value * scale
    except (InvalidOperation, ValueError):
        raise ValueError("A financial display claim needs a finite number and positive explicit scale.") from None
    return format(normalized, "f")


def _validate_component(record: Mapping[str, Any], key: str, currency: str) -> None:
    metric, kind = COMPONENT_CONTRACTS[key]
    if record.get("metric_key") != metric or record.get("claim_kind") != kind:
        raise ValueError("Financial claim metric or kind does not match its display component.")
    expected_unit = "percent" if key.startswith("ebitda_margin_") else currency
    if record.get("unit") != expected_unit:
        raise ValueError("Financial claim unit does not match its display component.")
    if expected_unit != "percent" and record.get("currency") != currency:
        raise ValueError("Financial claim currency does not match the reporting currency.")
    if record.get("business_unit") or record.get("scenario") or record.get("scenario_key"):
        raise ValueError("A scoped business-unit or scenario claim cannot become a group headline.")
    _normalized_value(record)


def _validate_presentation_record(record: Mapping[str, Any], currency: str) -> dict[str, Any]:
    dimensions = record.get("dimensions") if isinstance(record.get("dimensions"), Mapping) else {}
    component = str(dimensions.get("presentation_component") or "")
    expected_metric = {
        "trend": "ceo.presentation.trend",
        "contributor": "ceo.presentation.contributor",
        "cost_component": "ceo.presentation.cost_component",
    }.get(component)
    if expected_metric is None or record.get("metric_key") != expected_metric:
        raise ValueError("Financial presentation claim has an invalid component contract.")
    series = str(dimensions.get("series") or "")
    expected_kind = {"actual": "actual", "plan": "plan", "floor": "plan"}.get(series)
    if expected_kind is None or record.get("claim_kind") != expected_kind:
        raise ValueError("Financial presentation series does not match its governed claim kind.")
    unit = str(record.get("unit") or "")
    if unit not in {"SAR", "percent"}:
        raise ValueError("Financial presentation claim has an unsupported unit.")
    if unit == "SAR" and record.get("currency") != currency:
        raise ValueError("Financial presentation currency does not match the reporting currency.")
    if unit == "percent" and record.get("currency") not in {None, ""}:
        raise ValueError("A percentage presentation claim cannot carry a currency.")
    period = record.get("period") if isinstance(record.get("period"), Mapping) else {}
    if not period.get("start") or not period.get("end"):
        raise ValueError("Financial presentation claims require an exact period.")
    _normalized_value(record)
    return dict(dimensions)


def _sar_delta(value: Decimal) -> str:
    sign = "+" if value >= 0 else "−"
    magnitude = abs(value)
    if magnitude >= Decimal("1000000000"):
        shown = f"{magnitude / Decimal('1000000000'):.1f}B"
    elif magnitude >= Decimal("1000000"):
        shown = f"{magnitude / Decimal('1000000'):.1f}M"
    elif magnitude >= Decimal("1000"):
        shown = f"{magnitude / Decimal('1000'):.1f}K"
    else:
        shown = f"{magnitude:.0f}"
    return f"{sign}SAR {shown}"


def _presentation_projection(
    records: list[dict[str, Any]], currency: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    trend_rows: dict[tuple[str, str], list[tuple[int, str, Decimal, dict[str, Any]]]] = {}
    contributor_rows: dict[tuple[str, str], dict[str, tuple[Decimal, dict[str, Any], dict[str, Any]]]] = {}
    component_rows: dict[tuple[str, str], dict[str, tuple[Decimal, dict[str, Any], dict[str, Any]]]] = {}
    seen: set[tuple[Any, ...]] = set()
    for record in records:
        dimensions = _validate_presentation_record(record, currency)
        component = str(dimensions["presentation_component"])
        series = str(dimensions.get("series") or record.get("claim_kind") or "")
        value = Decimal(_normalized_value(record))
        if component == "trend":
            driver = str(dimensions.get("driver_key") or "")
            label = str(dimensions.get("label") or "")
            order = int(dimensions.get("order") or 0)
            identity = (component, driver, series, label)
            if not driver or not label or identity in seen:
                raise ValueError("Trend presentation claims are missing identity or compete for one point.")
            seen.add(identity)
            trend_rows.setdefault((driver, series), []).append((order, label, value, dimensions))
        elif component == "contributor":
            driver = str(dimensions.get("driver_key") or "")
            label = str(dimensions.get("label") or record.get("business_unit") or "")
            identity = (component, driver, label, series)
            if not driver or not label or identity in seen:
                raise ValueError("Contributor presentation claims are missing identity or compete.")
            seen.add(identity)
            contributor_rows.setdefault((driver, label), {})[series] = (value, dimensions, record)
        else:
            business_unit = str(dimensions.get("business_unit") or record.get("business_unit") or "")
            cost_component = str(dimensions.get("component") or "")
            identity = (component, business_unit, cost_component, series)
            if not business_unit or not cost_component or identity in seen:
                raise ValueError("Cost-component claims are missing identity or compete.")
            seen.add(identity)
            component_rows.setdefault((business_unit, cost_component), {})[series] = (value, dimensions, record)

    trend: dict[str, Any] = {}
    drivers = sorted({driver for driver, _series in trend_rows})
    for driver in drivers:
        actual_rows = sorted(trend_rows.get((driver, "actual"), []), key=lambda item: item[0])
        if not actual_rows:
            continue
        labels = [item[1] for item in actual_rows]
        item: dict[str, Any] = {
            "labels": labels,
            "actual": [format(row[2], "f") for row in actual_rows],
            "plan": [],
            "has_plan_series": False,
            "unit": "percent" if actual_rows[0][3].get("driver_key") == "ebitda_margin" else "sar",
        }
        for series in ("plan", "floor"):
            rows = sorted(trend_rows.get((driver, series), []), key=lambda row: row[0])
            if rows and [row[1] for row in rows] == labels:
                item[series] = [format(row[2], "f") for row in rows]
        item["has_plan_series"] = bool(item["plan"])
        notes = [str(row[3].get("note") or "") for row in actual_rows]
        if any(notes):
            item["notes"] = notes
        for key in ("scope_note", "plan_note"):
            value = str(actual_rows[0][3].get(key) or "")
            if value:
                item[key] = value
        trend[driver] = item

    dynamics: dict[str, Any] = {}
    contributors_by_driver: dict[str, list[dict[str, Any]]] = {}
    for (driver, label), lanes in contributor_rows.items():
        if "actual" not in lanes or "plan" not in lanes:
            continue
        actual, dimensions, _record = lanes["actual"]
        plan = lanes["plan"][0]
        variance = actual - plan
        if variance == 0:
            continue
        is_margin = driver == "ebitda_margin"
        favourable = variance > 0 if driver != "operating_cost" else variance < 0
        delta = (
            f"{'+' if variance > 0 else '−'}{abs(variance):.1f}pp vs plan"
            if is_margin
            else (
                f"{_sar_delta(abs(variance)).removeprefix('+')} {'above' if variance > 0 else 'below'} plan"
                if driver == "operating_cost"
                else _sar_delta(variance)
            )
        )
        row = {
            "name": label,
            "delta": delta,
            "magnitude": abs(variance),
            "lane": "lifting" if favourable else "dragging",
        }
        note = str(dimensions.get("note") or "")
        if note:
            row.update({"gm": "BU note", "note": note})
        contributors_by_driver.setdefault(driver, []).append(row)
    for driver, rows in contributors_by_driver.items():
        dynamics[driver] = {
            lane: [
                {key: value for key, value in row.items() if key not in {"magnitude", "lane"}}
                for row in sorted(
                    (item for item in rows if item["lane"] == lane),
                    key=lambda item: item["magnitude"],
                    reverse=True,
                )[:4]
            ]
            for lane in ("lifting", "dragging")
        }
        dynamics[driver]["scope_note"] = "Governed business-unit actual versus aligned plan."

    cost_rows: list[dict[str, Any]] = []
    for (business_unit, component), lanes in component_rows.items():
        if "actual" not in lanes or "plan" not in lanes:
            continue
        actual, dimensions, _record = lanes["actual"]
        plan = lanes["plan"][0]
        variance = actual - plan
        cost_rows.append(
            {
                "business_unit": business_unit,
                "component": component,
                "actual_sar": format(actual, "f"),
                "budget_sar": format(plan, "f"),
                "variance_sar": format(variance, "f"),
                "direction": "above_plan" if variance > 0 else "below_plan" if variance < 0 else "on_plan",
                "driver": str(dimensions.get("driver") or "") or None,
                "cross_ref": str(dimensions.get("cross_ref") or "") or None,
                "order": int(dimensions.get("order") or 0),
            }
        )
    cost_rows.sort(key=lambda row: (row["order"], row["business_unit"], row["component"]))
    cost_components = {
        "available": bool(cost_rows),
        "display_cap": 12,
        "ranked_by": "absolute governed H1 variance",
        "rows": [{key: value for key, value in row.items() if key != "order"} for row in cost_rows],
    }
    if not cost_rows:
        cost_components["unavailable_reason"] = "No authorized governed cost-component claims are available."
    return trend, dynamics, cost_components


def _contributor_rows_from_records(
    records: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, tuple[Decimal, dict[str, Any], dict[str, Any]]]]:
    result: dict[tuple[str, str], dict[str, tuple[Decimal, dict[str, Any], dict[str, Any]]]] = {}
    for record in records:
        dimensions = record.get("dimensions") if isinstance(record.get("dimensions"), Mapping) else {}
        if dimensions.get("presentation_component") != "contributor":
            continue
        driver = str(dimensions.get("driver_key") or "")
        label = str(dimensions.get("label") or record.get("business_unit") or "")
        series = str(dimensions.get("series") or record.get("claim_kind") or "")
        if driver and label and series in {"actual", "plan"}:
            result.setdefault((driver, label), {})[series] = (
                Decimal(_normalized_value(record)), dict(dimensions), record
            )
    return result


def _contributor_display_row(
    driver: str,
    lanes: dict[str, tuple[Decimal, dict[str, Any], dict[str, Any]]],
) -> dict[str, Any] | None:
    if "actual" not in lanes or "plan" not in lanes:
        return None
    actual, dimensions, _record = lanes["actual"]
    plan = lanes["plan"][0]
    variance = actual - plan
    row: dict[str, Any] = {
        "label": str(dimensions.get("label") or ""),
        "contributor_kind": str(dimensions.get("contributor_kind") or "business_unit"),
        "direction": "above_plan" if variance > 0 else "below_plan" if variance < 0 else "on_plan",
    }
    if driver == "ebitda_margin":
        row.update(
            {
                "value_percent": format(actual, "f"),
                "plan_percent": format(plan, "f"),
                "variance_pp": format(variance, "f"),
            }
        )
    else:
        row.update(
            {
                "value_sar": format(actual, "f"),
                "plan_sar": format(plan, "f"),
                "variance_sar": format(variance, "f"),
            }
        )
    note = str(dimensions.get("note") or "")
    if note:
        row["note"] = note
    return row


def finance_payload_from_claim_snapshot(
    legacy_payload: Mapping[str, Any] | None,
    snapshot: Mapping[str, Any],
    *,
    reconciliation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the finance read model exclusively from authorized immutable claims.

    Legacy payload fields may supply non-financial display copy, but headline,
    chart, mover and cost-component values are always removed and reconstructed
    from the policy-filtered snapshot. Missing governed claims remain missing.
    """
    payload = dict(legacy_payload or {})
    # Quarantined raw values belong to the governed inspection path, not a
    # legacy summary that bypasses per-claim authorization.
    payload.pop("ambiguous_components", None)
    payload.pop("trend", None)
    payload.pop("dynamics", None)
    payload.pop("actual_complete", None)
    components = dict(payload.get("components") or {})
    for key in COMPONENT_KEYS:
        components.pop(key, None)

    component_claims: dict[str, dict[str, Any]] = {}
    derived_claims: dict[str, dict[str, Any]] = {}
    presentation_records: list[dict[str, Any]] = []
    currency = str(payload.get("reporting_currency") or "SAR")
    if currency != "SAR":
        raise ValueError("This finance presentation supports SAR only; inspect other currencies in the claim workspace.")
    seen_components: set[str] = set()
    for raw_record in list(snapshot.get("records") or []):
        if not isinstance(raw_record, Mapping):
            continue
        record = dict(raw_record)
        dimensions = record.get("dimensions") if isinstance(record.get("dimensions"), Mapping) else {}
        if record.get("metric_key") in FINANCE_PRESENTATION_METRIC_KEYS:
            presentation_records.append(record)
            continue
        component_key = str(dimensions.get("component_key") or "").strip()
        if component_key in COMPONENT_CONTRACTS:
            _validate_component(record, component_key, currency)
            if component_key in seen_components:
                raise ValueError("Multiple claims compete for a financial headline; explicit resolution is required.")
            seen_components.add(component_key)
        if component_key in COMPONENT_KEYS:
            normalized = _normalized_value(record)
            if normalized is not None:
                components[component_key] = normalized
                component_claims[component_key] = record
        elif component_key in {"ebitda_margin_actual", "ebitda_margin_plan"}:
            derived_claims[component_key] = record

    # Never compare different reporting periods merely because component names
    # look compatible. Absence remains explicit; no dates are inferred here.
    for actual_key, plan_key in (("revenue_actual", "revenue_plan"),
                                 ("ebitda_actual", "ebitda_plan"),
                                 ("operating_cost_actual", "operating_cost_plan")):
        actual, plan = component_claims.get(actual_key), component_claims.get(plan_key)
        if actual and plan:
            def period(record: Mapping[str, Any]) -> tuple[Any, Any]:
                nested = record.get("period") or {}
                return (nested.get("start", record.get("period_start")),
                        nested.get("end", record.get("period_end")))
            if None in period(actual) or None in period(plan) or period(actual) != period(plan):
                raise ValueError("Actual and plan claim periods do not align.")

    trend, dynamics, cost_components = _presentation_projection(presentation_records, currency)
    legacy_evidence = dict(payload.get("evidence") or {})
    evidence: dict[str, dict[str, Any]] = {}
    for evidence_key in EVIDENCE_COMPONENTS:
        legacy_item = legacy_evidence.get(evidence_key)
        item = {
            key: value
            for key, value in (dict(legacy_item).items() if isinstance(legacy_item, Mapping) else [])
            if key not in {"details", "files", "claim_revisions", "claim_labels", "governed_sources"}
        }
        evidence[evidence_key] = item
    for evidence_key, keys in EVIDENCE_COMPONENTS.items():
        item = evidence.setdefault(evidence_key, {})
        linked = [component_claims[key] for key in keys if key in component_claims]
        driver_presentation = [
            record
            for record in presentation_records
            if str((record.get("dimensions") or {}).get("driver_key") or "") == evidence_key
        ]
        governed_records = linked + driver_presentation
        item["claim_revisions"] = [record["claim_revision_id"] for record in linked]
        item["claim_labels"] = [record["label"] for record in linked]
        item["governed_sources"] = [
            source
            for record in governed_records
            for source in list(record.get("sources") or [])
            if isinstance(source, Mapping)
        ]
        item["files"] = sorted(
            {
                str(source.get("original_uri"))
                for source in item["governed_sources"]
                if str(source.get("original_uri") or "").strip()
            }
        )
        grouped_contributors = _contributor_rows_from_records(driver_presentation)
        contributor_items = [
            (int(lanes.get("actual", (Decimal(0), {}, {}))[1].get("order") or 0), row)
            for (driver, _label), lanes in grouped_contributors.items()
            if driver == evidence_key
            for row in [_contributor_display_row(driver, lanes)]
            if row is not None
        ]
        contributor_items.sort(key=lambda item: item[0])
        contributor_rows = [row for _order, row in contributor_items]
        if evidence_key != "ebitda_margin":
            total = sum((Decimal(str(row["value_sar"])) for row in contributor_rows), Decimal())
            for row in contributor_rows:
                row["share_pct"] = (
                    float((Decimal(str(row["value_sar"])) / total * 100).quantize(Decimal("0.1")))
                    if total
                    else None
                )
        contributors = {evidence_key: contributor_rows}
        item["details"] = {"contributors": contributors}
        if evidence_key == "operating_cost":
            item["details"]["cost_components"] = cost_components

    actual_complete = {
        evidence_key: all(
            key in component_claims and str(component_claims[key].get("traceability")) == "present"
            for key in keys
            if key not in {"revenue_plan", "ebitda_plan", "operating_cost_plan", "board_floor"}
        )
        for evidence_key, keys in EVIDENCE_COMPONENTS.items()
    }

    result = {
        **payload,
        "authoritative": bool(component_claims),
        "derived_from": "governed_claim_snapshot",
        "components": components,
        "component_claims": component_claims,
        "derived_claims": derived_claims,
        "evidence": evidence,
        "trend": trend,
        "dynamics": dynamics,
        "actual_complete": actual_complete,
        "claim_snapshot": {
            "snapshot_id": snapshot.get("snapshot_id"),
            "snapshot_key": snapshot.get("snapshot_key"),
            "analysis_as_of": snapshot.get("analysis_as_of"),
            "policy_version": snapshot.get("policy_version"),
            "denied_count": int(snapshot.get("denied_count") or 0),
        },
        "canonical_claim_status": "ready" if component_claims else "no_headline_claims",
    }
    if reconciliation:
        result["claim_reconciliation"] = dict(reconciliation)
    return result
