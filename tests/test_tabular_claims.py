from io import BytesIO

import pytest
from openpyxl import Workbook

from strategyos_mvp.tabular_claims import TableClaimMapping, map_table, read_workbook_rows


def mapping(**changes):
    value = dict(mapping_key="finance", mapping_version="1", rationale="Finance-approved column definitions",
        sheet="Finance", subject_type="business_unit", subject_key_column="BU",
        period_start_column="From", period_end_column="To", columns=[
            dict(column="Value", metric_key="cost", kind_column="Kind", unit="SAR", scale=1, currency="SAR",
                 author_column="Author")])
    value.update(changes)
    return TableClaimMapping(**value)


def mapped(rows, **changes):
    return map_table(rows, mapping(**changes), tenant_id="tenant", source_key="erp",
                     occurrence_key="occurrence", recorded_by="steward")


def row(**changes):
    result = {"BU": "retail", "From": "2026-06-01", "To": "2026-06-30",
              "Value": 0, "Kind": "actual", "Author": None}
    result.update(changes)
    return result


def test_explicit_kinds_and_zero_are_preserved_without_inference():
    result = mapped([row(), row(Kind="plan", Value=5), row(Kind="forecast", Value=-3, Author="CFO")])
    assert [str(d.claim_kind) for d in result["drafts"]] == ["actual", "plan", "forecast"]
    assert [d.value_numeric for d in result["drafts"]] == [0, 5, -3]
    assert result["issues"] == []
    assert all(d.business_unit == "retail" for d in result["drafts"])


@pytest.mark.parametrize("changes,reason", [
    ({"Kind": "Actual/Forecast"}, "claim_kind_ambiguous"),
    ({"Kind": "forecast"}, "forecast_author_missing"),
    ({"From": ""}, "period_unresolved"),
    ({"To": "2026-05-01"}, "period_unresolved"),
    ({"Value": "1,234"}, "numeric_value_invalid"),
    ({"Value": True}, "numeric_value_invalid"),
    ({"Value": "NaN"}, "numeric_value_invalid"),
])
def test_ambiguous_cells_are_accounted_for_but_never_actuals(changes, reason):
    result = mapped([row(**changes)])
    assert str(result["drafts"][0].claim_kind) == "unknown"
    assert result["quarantined_count"] == 1
    assert reason in result["drafts"][0].metadata["quarantine_reasons"]


def test_missing_values_do_not_become_zero_and_unresolved_subjects_are_accounted():
    result = mapped([row(Value=None), row(BU=""), row(BU=0)])
    assert result["source_cell_count"] == 3
    assert result["unmapped_count"] == 2
    assert result["drafts"][0].subject_key == "0"


def test_mapping_version_changes_revision_not_family():
    old = mapped([row()])["drafts"][0]
    new = mapped([row()], mapping_version="2")["drafts"][0]
    assert old.family_key == new.family_key
    assert old.fingerprint != new.fingerprint


def workbook(rows):
    book = Workbook()
    book.active.title = "Finance"
    for item in rows:
        book.active.append(item)
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def test_workbook_preserves_internal_blank_rows_and_cell_locators():
    content = workbook([["BU", "From", "To", "Value", "Kind", "Author"],
        ["retail", "2026-06-01", "2026-06-30", 4, "actual", None], [],
        ["retail", "2026-06-01", "2026-06-30", 6, "plan", None]])
    result = mapped(read_workbook_rows(content, mapping()))
    assert result["drafts"][1].metadata["source_locator"] == "Finance!row 4; column Value"
    assert result["missing_count"] == 1


def test_duplicate_headers_are_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        read_workbook_rows(workbook([["BU", "BU"]]), mapping())


def test_formula_without_cached_value_is_missing_not_a_fabricated_number():
    content = workbook([["BU", "From", "To", "Value", "Kind", "Author"],
        ["retail", "2026-06-01", "2026-06-30", "=2+2", "actual", None]])
    assert mapped(read_workbook_rows(content, mapping()))["missing_count"] == 1
