"""Multi-year context, read from the files the dataset already supplies.

The current run computes H1 2026 actuals from the current-period ledgers. When
an executive asks "how did revenue grow over three years?", that question is
about history the run does not calculate but the dataset does carry -- a
strategic-analytics annual summary, a group revenue-driver sheet. Those files
are normalized into the run's historic-context area but were never surfaced to
the assistant, so it answered "no historic data" while holding the answer.

This reads them back into a compact, governed summary: annual revenue by year
with its stated commentary, and the named drivers of change. It derives
nothing -- every figure and phrase comes from a supplied file, cited by name.
When the files are absent (an older or minimal dataset), it returns an explicit
empty result and the assistant keeps saying history is unavailable rather than
inventing a trend.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

try:  # pandas is always present in the run environment; guard keeps import safe
    import pandas as pd
except Exception:  # pragma: no cover - pandas missing is a broken environment
    pd = None  # type: ignore[assignment]


def _find(root: Path, *fragments: str) -> Path | None:
    """First file under root whose name contains all fragments (case-insensitive)."""
    wanted = [fragment.lower() for fragment in fragments]
    for path in sorted(root.rglob("*.xlsx")) + sorted(root.rglob("*.csv")):
        name = path.name.lower()
        if all(fragment in name for fragment in wanted):
            return path
    return None


def _sheet(path: Path, *name_fragments: str):
    if pd is None:
        return None
    try:
        book = pd.ExcelFile(path)
    except Exception:
        return None
    wanted = [fragment.lower() for fragment in name_fragments]
    for sheet_name in book.sheet_names:
        if all(fragment in str(sheet_name).lower() for fragment in wanted):
            try:
                return book.parse(sheet_name)
            except Exception:
                return None
    return None


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _annual_revenue(root: Path) -> dict[str, Any] | None:
    """The year-by-year net revenue trend from the strategic annual summary."""
    path = _find(root, "revenue", "analytics")
    if path is None:
        return None
    frame = _sheet(path, "annual")
    if frame is None or frame.empty:
        return None
    year_col = next((c for c in frame.columns if str(c).strip().lower() == "year"), None)
    rev_col = next(
        (c for c in frame.columns if "net revenue" in str(c).lower()),
        None,
    )
    if year_col is None or rev_col is None:
        return None
    yoy_col = next((c for c in frame.columns if "yoy" in str(c).lower()), None)
    note_col = next((c for c in frame.columns if "comment" in str(c).lower()), None)

    series: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        year = str(row.get(year_col) or "").strip()
        revenue = _num(row.get(rev_col))
        if not year or revenue is None:
            continue
        series.append(
            {
                "year": year,
                "net_revenue_sar_m": revenue,
                "yoy": str(row.get(yoy_col) or "").strip() if yoy_col else None,
                "commentary": str(row.get(note_col) or "").strip() if note_col else None,
            }
        )
    if len(series) < 2:
        return None
    return {"source_file": path.name, "series": series}


def _revenue_drivers(root: Path) -> dict[str, Any] | None:
    """Named drivers of revenue change, from the group financials driver sheet."""
    path = _find(root, "pnl") or _find(root, "group", "financ") or _find(root, "bu_pnl")
    if path is None:
        return None
    frame = _sheet(path, "driver")
    if frame is None or frame.empty:
        return None
    driver_col = next((c for c in frame.columns if "driver" in str(c).lower()), None)
    impact_col = next((c for c in frame.columns if "impact" in str(c).lower() or "sar m" in str(c).lower()), None)
    year_col = next((c for c in frame.columns if str(c).strip().lower() == "year"), None)
    if driver_col is None:
        return None
    drivers: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        driver = str(row.get(driver_col) or "").strip()
        if not driver:
            continue
        drivers.append(
            {
                "year": str(row.get(year_col) or "").strip() if year_col else None,
                "driver": driver,
                "impact_sar_m": _num(row.get(impact_col)) if impact_col else None,
            }
        )
    if not drivers:
        return None
    return {"source_file": path.name, "drivers": drivers}


def derive_historic_context(dataset_root: Path | str) -> dict[str, Any]:
    """Return the multi-year context the dataset supplies, or an explicit absence.

    Looks across the whole dataset root -- the strategic files land in the run's
    historic-context area, so rglob finds them wherever normalization placed
    them. Nothing is computed from the current-period actuals.
    """
    root = Path(dataset_root)
    if not root.exists():
        return {"available": False, "reason": "No dataset root to read historic context from."}

    annual = _annual_revenue(root)
    drivers = _revenue_drivers(root)
    if not annual and not drivers:
        return {
            "available": False,
            "reason": "This dataset carries no multi-year revenue analytics or driver history.",
        }

    sources = sorted(
        {item["source_file"] for item in (annual, drivers) if item}
    )
    payload: dict[str, Any] = {
        "available": True,
        "basis": "Read from the dataset's strategic-analytics and group-financial files; not derived from the current-period actuals.",
        "source_files": sources,
    }
    if annual:
        payload["annual_revenue"] = annual["series"]
    if drivers:
        payload["revenue_drivers"] = drivers["drivers"]
    return payload
