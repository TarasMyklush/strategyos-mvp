"""Compile a governed source pack into Intent structure, plan and actual contracts.

The compiler is sector-neutral at runtime: every dimension and member comes from
the supplied pack. It verifies registered bytes, records every transformation,
and stages proposals through the existing independent approval boundaries.
"""
from __future__ import annotations

import calendar
import csv
from collections import defaultdict
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

import openpyxl
import yaml

from . import dimensional_intent_store as intent
from . import tenant_structure_store
from .dimensional_intent_sources import SourceUnavailable, authorize_source_policy
from .dimensional_plan import Actuals, Plan
from .source_governance import CONTROL_PLANE, CURRENT_EVIDENCE, HISTORIC_CONTEXT
from .tenant_structure import TenantStructureConfiguration


REQUIRED_FILES = {
    "dimension_config": "Dimension_Config_v1.yaml",
    "plan_structure": "Plan_Decomposition_Structure_v1.json",
    "plan": "Plan_Data_2026.csv",
    "actuals": "Sales_Cube_Monthly_2025-2026H1.csv",
    "products": "SKU_Master_Cube.xlsx",
    "clients": "Client_Master_Cube.xlsx",
}
PLAN_COLUMNS = {
    "Structure_Version", "Month", "Region", "Channel", "Family_Code", "Family",
    "Plan_Gross_Revenue_SAR",
}
ACTUAL_COLUMNS = {
    "Month", "Region", "Channel", "Client_ID", "SKU", "Family_Code", "Family",
    "Gross_Revenue_SAR",
}


def _registered_package(principal: dict[str, Any], source_pack_id: str):
    tenant, _ = intent._scope(principal, intent.IMPORT_ROLES)
    intent._key(source_pack_id)
    base = (intent.CONFIG.output_root / "source_packs").resolve()
    directory = (base / source_pack_id).resolve()
    if directory.parent != base or directory.is_symlink():
        raise SourceUnavailable("Invalid source pack identifier.")
    try:
        summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SourceUnavailable("Registered source pack metadata is unavailable.") from exc
    if summary.get("source_pack_id") != source_pack_id or (summary.get("tenant_context") or {}).get("tenant_id") != tenant:
        raise PermissionError("Source pack not found in this tenant.")
    source_key = str((summary.get("source_contract") or {}).get("source_key") or "")
    authorize_source_policy(tenant, source_key, principal, "operations")
    raw_root = (directory / "raw").resolve()
    if raw_root != directory / "raw" or not raw_root.is_dir():
        raise SourceUnavailable("Registered source bytes are unavailable.")
    manifest = summary.get("manifest") or []
    resolved: dict[str, dict[str, Any]] = {}
    for logical, filename in REQUIRED_FILES.items():
        matches = [item for item in manifest if PurePosixPath(str(item.get("relative_path") or "")).name == filename]
        if len(matches) != 1:
            raise SourceUnavailable(f"The source pack must contain exactly one {filename} file.")
        item = matches[0]
        disposition = item.get("source_disposition")
        allowed = {CONTROL_PLANE} if logical in {"dimension_config", "plan_structure", "products", "clients"} else {
            CURRENT_EVIDENCE, HISTORIC_CONTEXT,
        }
        if item.get("supported") is not True or disposition not in allowed:
            raise SourceUnavailable(f"{filename} is not eligible for governed plan compilation.")
        relative = str(item["relative_path"])
        path = (raw_root / relative).resolve()
        if path.parent == raw_root or not path.is_relative_to(raw_root) or not path.is_file() or path.is_symlink():
            raise SourceUnavailable(f"Registered bytes for {filename} are unavailable.")
        digest = sha256(path.read_bytes()).hexdigest()
        if digest != item.get("sha256"):
            raise SourceUnavailable(f"Registered bytes for {filename} failed integrity verification.")
        resolved[logical] = {"path": path, "relative_path": relative, "sha256": digest}
    return tenant, source_key, resolved


def _rows(path: Path, required: set[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            missing = sorted(required - set(reader.fieldnames or []))
            raise ValueError("The source table is missing required columns: " + ", ".join(missing) + ".")
        result = [{key: str(value or "").strip() for key, value in row.items()} for row in reader]
    if not result or any(any(not row[column] for column in required) for row in result):
        raise ValueError("The source table contains missing required values.")
    return result


def _workbook_rows(path: Path) -> list[dict[str, Any]]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.active
    values = sheet.iter_rows(values_only=True)
    headings = [str(value or "").strip() for value in next(values)]
    return [dict(zip(headings, row)) for row in values if any(value is not None for value in row)]


def _translation(en: str, ar: str | None = None) -> dict[str, str]:
    return {"en": en[:100], "ar": (ar or en)[:100]}


def _member(key: str, label: str | None = None, parent: str | None = None) -> dict[str, Any]:
    return {"key": key, "label": _translation(label or key), "parent": parent}


def _objective_total(text: str) -> Decimal:
    match = re.search(r"SAR\s*([0-9][0-9,]*(?:\.[0-9]+)?)M\b", text, re.IGNORECASE)
    if not match:
        raise ValueError("The plan objective must state its approved SAR amount in millions.")
    return Decimal(match.group(1).replace(",", "")) * Decimal("1000000")


def _branch_owners(structure: dict[str, Any]):
    owners: dict[str, dict[str, str]] = defaultdict(dict)
    for branch in structure.get("branches") or []:
        key, separator, member = str(branch.get("branch") or "").partition(":")
        owner = str(branch.get("owner") or "").strip()
        if not separator or not member or not owner:
            raise ValueError("Every declared plan branch requires a member and accountable owner.")
        owners[key][member] = owner
    return owners


def _cell_owner(row: dict[str, str], owners: dict[str, dict[str, str]]) -> str:
    channel = owners.get("channel", {}).get(row["Channel"])
    if channel:
        return channel
    family = owners.get("family", {}).get(row["Family"])
    if family and "/" not in family:
        return family
    region = owners.get("region", {}).get(row["Region"])
    if region:
        return region
    raise ValueError("No unambiguous accountable owner resolves for " + row["Region"] + ".")


def _last_day(month: str) -> date:
    year, number = (int(value) for value in month.split("-"))
    return date(year, number, calendar.monthrange(year, number)[1])


def _cell_id(row: dict[str, str]) -> str:
    return " | ".join((row["Month"], row["Region"], row["Channel"], row["Family"]))


def compile_package(principal: dict[str, Any], source_pack_id: str, cell_tolerance: Decimal):
    if cell_tolerance < 0:
        raise ValueError("Cell tolerance cannot be negative.")
    tenant, source_key, files = _registered_package(principal, source_pack_id)
    try:
        dimension_config = yaml.safe_load(files["dimension_config"]["path"].read_text(encoding="utf-8"))
        plan_structure = json.loads(files["plan_structure"]["path"].read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ValueError("The plan configuration files are not valid structured data.") from exc
    if not isinstance(dimension_config, dict) or not isinstance(plan_structure, dict):
        raise ValueError("The plan configuration files must contain objects.")
    plan_rows = _rows(files["plan"]["path"], PLAN_COLUMNS)
    actual_rows = _rows(files["actuals"]["path"], ACTUAL_COLUMNS)
    products = _workbook_rows(files["products"]["path"])
    clients = _workbook_rows(files["clients"]["path"])

    structure_id = str(plan_structure.get("structure_id") or "").strip()
    objective = str(plan_structure.get("objective") or "").strip()
    if not structure_id or not objective:
        raise ValueError("The plan structure must declare its identifier and objective.")
    versions = {row["Structure_Version"] for row in plan_rows}
    if versions != {structure_id}:
        raise ValueError("Every plan row must reference the declared structure version.")
    dimensions = {
        "month": sorted({row["Month"] for row in plan_rows}),
        "region": sorted({row["Region"] for row in plan_rows}),
        "channel": sorted({row["Channel"] for row in plan_rows}),
        "product": sorted({row["Family"] for row in plan_rows}),
    }
    configured_dimensions = {
        str(item.get("name") or "").strip(): item
        for item in dimension_config.get("dimensions") or [] if isinstance(item, dict)
    }
    if not {"product", "region", "channel", "client"}.issubset(configured_dimensions):
        raise ValueError("The dimension configuration must declare product, region, channel and client.")
    declared_splits = {
        "product" if value == "sku_family" else str(value)
        for value in plan_structure.get("decomposes_along") or []
    }
    if declared_splits != set(dimensions):
        raise ValueError("The decomposition dimensions do not match the granular plan columns.")
    for key in ("region", "channel"):
        declared_values = {str(value) for value in configured_dimensions[key].get("values") or []}
        if declared_values != set(dimensions[key]):
            raise ValueError(f"The {key} members differ between configuration and plan data.")
    declared_families = {str(value) for value in configured_dimensions["product"].get("families") or []}
    if declared_families != set(dimensions["product"]):
        raise ValueError("The product families differ between configuration and plan data.")
    tuples = {(row["Month"], row["Region"], row["Channel"], row["Family"]) for row in plan_rows}
    expected = len(dimensions["month"]) * len(dimensions["region"]) * len(dimensions["channel"]) * len(dimensions["product"])
    if len(plan_rows) != expected or len(tuples) != expected:
        raise ValueError("The granular plan is not a complete month-by-region-by-channel-by-product matrix.")
    owners = _branch_owners(plan_structure)
    if set(dimensions["region"]) - set(owners.get("region", {})):
        raise ValueError("Every region requires a named default owner.")

    objective_total = _objective_total(objective)
    source_total = sum((Decimal(row["Plan_Gross_Revenue_SAR"]) for row in plan_rows), Decimal(0))
    cells = []
    for index, row in enumerate(plan_rows, start=2):
        cells.append({
            "id": _cell_id(row), "metric": "revenue",
            "dimensions": {"month": row["Month"], "region": row["Region"],
                           "channel": row["Channel"], "product": row["Family"]},
            "owner": _cell_owner(row, owners), "target": row["Plan_Gross_Revenue_SAR"],
            "tolerance": str(cell_tolerance),
            "source": {"path": files["plan"]["relative_path"],
                       "locator": f"row {index}, Plan_Gross_Revenue_SAR", "sha256": files["plan"]["sha256"]},
        })
    cells.sort(key=lambda item: item["id"])
    adjustment = objective_total - source_total
    rounding_cell = cells[-1]
    rounding_cell["target"] = str(Decimal(rounding_cell["target"]) + adjustment)
    rounding_cell["source"]["locator"] += f"; {adjustment:+} SAR deterministic objective remainder"

    config = dimension_config.get("config") or {}
    config_id = str(config.get("id") or "").strip()
    if not config_id:
        raise ValueError("The dimension configuration must declare config.id.")
    version_text = str(config.get("version") or "1")
    config_version = int(version_text.split(".", 1)[0])
    org_unit = str(config.get("org_unit") or "").strip()
    if not org_unit:
        raise ValueError("The dimension configuration must declare config.org_unit.")
    bu_match = re.search(r"\(([^()]+)\)\s*$", org_unit)
    business_unit = bu_match.group(1) if bu_match else "business-unit"
    business_label = re.sub(r"\s*\([^()]+\)\s*$", "", org_unit).strip()
    configured_by = str(config.get("configured_by") or "").strip()
    company_match = re.search(r"\(([^()]+)\)\s*$", configured_by)
    company_label = company_match.group(1) if company_match else business_label

    product_members = {_member(row["Family"], row["Family"]) ["key"]: _member(row["Family"], row["Family"])
                       for row in products if row.get("Family")}
    for row in products:
        if row.get("SKU") and row.get("Family"):
            product_members[str(row["SKU"])] = _member(str(row["SKU"]), str(row.get("Description") or row["SKU"]), str(row["Family"]))
    client_members = [_member(str(row["Client_ID"]), str(row.get("Client_Name") or row["Client_ID"]))
                      for row in clients if row.get("Client_ID")]
    structure_dimensions = [
        {"key": "month", "label": _translation("Month", "الشهر"),
         "members": [_member(value) for value in dimensions["month"]]},
        {"key": "region", "label": _translation("Region", "المنطقة"),
         "members": [_member(value) for value in dimensions["region"]]},
        {"key": "channel", "label": _translation("Channel", "القناة"),
         "members": [_member(value) for value in dimensions["channel"]]},
        {"key": "product", "label": _translation("Product", "المنتج"),
         "members": list(product_members.values())},
        {"key": "client", "label": _translation("Client", "العميل"), "members": client_members},
    ]
    mappings = [
        {"source_key": source_key, "source_field": "Structure_Version", "target_type": "business_unit",
         "values": [{"source_value": structure_id, "target": business_unit}]},
        *[{"source_key": source_key, "source_field": field, "target_type": "dimension", "target_key": key,
           "values": [{"source_value": value, "target": value} for value in values]}
          for key, field, values in (("month", "Month", dimensions["month"]),
                                     ("region", "Region", dimensions["region"]),
                                     ("channel", "Channel", dimensions["channel"]),
                                     ("product", "Family", dimensions["product"]),
                                     ("client", "Client_ID", [item["key"] for item in client_members]))],
    ]
    structure = TenantStructureConfiguration.model_validate({
        "schema_version": 1, "config_id": config_id, "version": config_version,
        "company": _translation(company_label),
        "business_units": [{"key": business_unit,
                            "label": _translation(business_label)}],
        "dimensions": structure_dimensions, "source_mappings": mappings,
    })
    structure_digest = intent.fingerprint(structure.model_dump(mode="json"))
    start = date.fromisoformat(dimensions["month"][0] + "-01")
    end = _last_day(dimensions["month"][-1])
    plan_id = re.sub(r"[^a-z0-9_.-]+", "-", structure_id.lower()).strip("-") + "-plan"
    plan = Plan.model_validate({
        "schema_version": 1, "plan_id": plan_id, "company_id": tenant,
        "version": 1, "period": {"start": start, "end": end},
        "effective_from": start, "effective_to": end, "status": "proposed",
        "business_unit": business_unit,
        "structure": {"config_id": config_id, "version": config_version, "digest": structure_digest},
        "dimensions": dimensions,
        "metrics": {"revenue": {"unit": "SAR", "aggregation": "sum",
                                  "direction": "higher_is_better", "planned_total": str(objective_total),
                                  "tolerance": str(cell_tolerance)}},
        "cells": cells, "display_name": objective, "period_dimension": "month",
        "catalog_visibility": "customer",
        "source_import": {"compiler_version": "source-plan-package.v1", "source_structure_id": structure_id,
                          "source_row_count": len(plan_rows), "source_total": str(source_total),
                          "approved_objective_total": str(objective_total),
                          "rounding_adjustment": str(adjustment), "rounding_cell_id": rounding_cell["id"],
                          "rounding_rule": "final_lexicographic_cell",
                          "owner_rule": "channel override, then unambiguous family override, then region owner",
                          "cell_tolerance": str(cell_tolerance),
                          "scope": f"{business_label}; {start.year} full-year plan"},
    })

    matching_actuals = [row for row in actual_rows if row["Month"].startswith(str(start.year) + "-")]
    if not matching_actuals:
        raise ValueError("The actual cube contains no observations for the plan year.")
    grouped: dict[tuple[str, str, str, str], Decimal] = defaultdict(Decimal)
    counts: dict[tuple[str, str, str, str], int] = defaultdict(int)
    for row in matching_actuals:
        key = (row["Month"], row["Region"], row["Channel"], row["Family"])
        grouped[key] += Decimal(row["Gross_Revenue_SAR"])
        counts[key] += 1
    actual_months = sorted({key[0] for key in grouped})
    actual_expected = len(actual_months) * len(dimensions["region"]) * len(dimensions["channel"]) * len(dimensions["product"])
    if len(grouped) != actual_expected:
        raise ValueError("The actual cube does not cover every planned cell in its reported months.")
    observations = []
    for key in sorted(grouped):
        month, region, channel, product = key
        observations.append({
            "metric": "revenue", "dimensions": {"month": month, "region": region,
                                                   "channel": channel, "product": product},
            "unit": "SAR", "value": str(grouped[key]),
            "source": {"path": files["actuals"]["relative_path"],
                       "locator": (f"Month={month}; Region={region}; Channel={channel}; Family={product}; "
                                   f"sum Gross_Revenue_SAR across {counts[key]} source rows"),
                       "sha256": files["actuals"]["sha256"]},
        })
    actual_end = _last_day(actual_months[-1])
    actuals = Actuals.model_validate({
        "schema_version": 1, "company_id": tenant, "kind": "actual",
        "revision": f"{plan_id}-actuals-through-{actual_months[-1]}",
        "period": {"start": date.fromisoformat(actual_months[0] + "-01"), "end": actual_end},
        "recorded_on": actual_end, "observations": observations,
    })
    return {"structure": structure, "plan": plan, "actuals": actuals,
            "source_pack_id": source_pack_id, "source_key": source_key,
            "assertions": {"plan_rows": len(plan_rows), "plan_source_total": str(source_total),
                           "objective_total": str(objective_total), "rounding_adjustment": str(adjustment),
                           "actual_source_rows": len(matching_actuals), "actual_cells": len(observations)}}


def import_package(principal: dict[str, Any], source_pack_id: str, cell_tolerance: Decimal):
    compiled = compile_package(principal, source_pack_id, cell_tolerance)
    structure = compiled["structure"]
    try:
        record = tenant_structure_store.read(principal, structure.config_id, structure.version)
    except intent.NotFound:
        record = tenant_structure_store.create(principal, structure)
        return {"status": "awaiting_structure_approval", "structure": _structure_summary(record),
                "assertions": compiled["assertions"]}
    if record["digest"] != intent.fingerprint(structure.model_dump(mode="json")):
        raise intent.Conflict("The approved structure identifier is already used by different content.")
    if not record["authoritative"]:
        return {"status": "awaiting_structure_approval", "structure": _structure_summary(record),
                "assertions": compiled["assertions"]}
    plan_record = intent.import_plan(principal, compiled["plan"], source_pack_id)
    actual_record = intent.import_actuals(principal, compiled["actuals"], source_pack_id)
    return {"status": "awaiting_plan_ratification",
            "plan": {key: plan_record[key] for key in ("plan_id", "version", "digest", "imported_at")},
            "actuals": {key: actual_record[key] for key in ("revision", "digest", "imported_at")},
            "structure": _structure_summary(record), "assertions": compiled["assertions"]}


def _structure_summary(record: dict[str, Any]):
    return {key: record[key] for key in ("config_id", "version", "digest", "authoritative")}
