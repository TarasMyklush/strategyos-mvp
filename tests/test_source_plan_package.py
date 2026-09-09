import csv
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json

import openpyxl

from strategyos_mvp import source_plan_package
from strategyos_mvp.dimensional_plan import evaluate


def _write_table(path, headings, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headings)
        writer.writeheader()
        writer.writerows(rows)


def _write_book(path, headings, rows):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(headings)
    for row in rows:
        sheet.append(row)
    workbook.save(path)


def _package(tmp_path, monkeypatch):
    root = tmp_path / "24_Sales_Cube"
    root.mkdir()
    (root / "Dimension_Config_v1.yaml").write_text(
        "config:\n  id: DIMCFG-TEST-001\n  version: '1.0'\n  org_unit: 'Test Distribution (BU02)'\n  configured_by: 'Advisor (Test Group)'\n"
        "dimensions:\n"
        "  - name: product\n    families: [Generics, Specialty]\n"
        "  - name: region\n    values: [Central, Western]\n"
        "  - name: channel\n    values: [Retail pharmacy]\n"
        "  - name: client\n    values_source: Client_Master_Cube.xlsx\n",
        encoding="utf-8",
    )
    (root / "Plan_Decomposition_Structure_v1.json").write_text(json.dumps({
        "structure_id": "PD-TEST-2026-v1",
        "objective": "Test Distribution FY2026 revenue plan — SAR 100M",
        "decomposes_along": ["month", "region", "channel", "sku_family"],
        "branches": [
            {"branch": "region:Central", "owner": "Central owner", "assumption": "Approved."},
            {"branch": "region:Western", "owner": "Western owner", "assumption": "Approved."},
        ],
    }), encoding="utf-8")
    plan_rows = []
    combinations = [
        (month, region, "Retail pharmacy", code, family)
        for month in ("2026-01", "2026-02")
        for region in ("Central", "Western")
        for code, family in (("GEN", "Generics"), ("SPC", "Specialty"))
    ]
    for index, (month, region, channel, code, family) in enumerate(combinations):
        amount = "12500000.03" if index == len(combinations) - 1 else "12500000.00"
        plan_rows.append({"Structure_Version": "PD-TEST-2026-v1", "Month": month,
                          "Region": region, "Channel": channel, "Family_Code": code,
                          "Family": family, "Plan_Gross_Revenue_SAR": amount})
    _write_table(root / "Plan_Data_2026.csv", list(plan_rows[0]), plan_rows)
    actual_rows = []
    for region in ("Central", "Western"):
        for code, family, sku in (("GEN", "Generics", "SKU-G"), ("SPC", "Specialty", "SKU-S")):
            actual_rows.append({"Month": "2026-01", "Region": region, "Channel": "Retail pharmacy",
                                "Client_ID": "CLIENT-1", "SKU": sku, "Family_Code": code,
                                "Family": family, "Gross_Revenue_SAR": "13000000.00"})
    _write_table(root / "Sales_Cube_Monthly_2025-2026H1.csv", list(actual_rows[0]), actual_rows)
    _write_book(root / "SKU_Master_Cube.xlsx", ["SKU", "Family_Code", "Family", "Description"], [
        ["SKU-G", "GEN", "Generics", "Generic product"],
        ["SKU-S", "SPC", "Specialty", "Specialty product"],
    ])
    _write_book(root / "Client_Master_Cube.xlsx", ["Client_ID", "Client_Name"], [
        ["CLIENT-1", "Test client"],
    ])
    files = {}
    for logical, filename in source_plan_package.REQUIRED_FILES.items():
        path = root / filename
        files[logical] = {"path": path, "relative_path": f"24_Sales_Cube/{filename}",
                          "sha256": sha256(path.read_bytes()).hexdigest()}
    monkeypatch.setattr(source_plan_package, "_registered_package",
                        lambda principal, pack_id: ("tenant-a", "source-a", files))
    return source_plan_package.compile_package({"role": "operator"}, "pack-a", Decimal("0"))


def test_source_plan_package_compiles_complete_plan_and_discloses_rounding(tmp_path, monkeypatch):
    package = _package(tmp_path, monkeypatch)

    plan = package["plan"]
    assert len(plan.cells) == 8
    assert plan.metrics["revenue"].planned_total == Decimal("100000000")
    assert sum((cell.target for cell in plan.cells), Decimal(0)) == Decimal("100000000")
    assert plan.source_import.source_total == Decimal("100000000.03")
    assert plan.source_import.rounding_adjustment == Decimal("-0.03")
    assert plan.source_import.rounding_cell_id == sorted(cell.id for cell in plan.cells)[-1]
    assert {cell.owner for cell in plan.cells} == {"Central owner", "Western owner"}
    assert plan.catalog_visibility == "customer"
    assert {dimension.key for dimension in package["structure"].dimensions} == {
        "month", "region", "channel", "product", "client",
    }


def test_source_plan_package_actuals_compare_to_matching_months_of_full_year_plan(tmp_path, monkeypatch):
    package = _package(tmp_path, monkeypatch)

    result = evaluate(package["plan"], package["actuals"], source_root=tmp_path,
                      company_id="tenant-a", as_of=date(2026, 1, 31))

    assert result["partial_period"] is True
    assert result["period"] == {"start": "2026-01-01", "end": "2026-01-31"}
    assert result["plan_period"] == {"start": "2026-01-01", "end": "2026-02-28"}
    assert result["rollups"][0]["target"] == "50000000.00"
    assert result["rollups"][0]["actual"] == "52000000.00"
    assert result["rollups"][0]["variance"] == "2000000.00"
    assert result["rollups"][0]["planned_cells"] == 4
    assert result["rollups"][0]["measured_cells"] == 4
