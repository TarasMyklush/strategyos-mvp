"""Deterministic CEO finance KPIs from the files supplied with a run.

This adapter intentionally does not pretend that an uploaded spreadsheet is an
Oracle snapshot.  It derives only the four CEO actuals that can be reproduced
from the source pack, and keeps the selected files, accounts and row coverage
with the result so the presentation and Hermes can explain every number.
"""

from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping

from openpyxl import load_workbook


def derive_source_finance_kpis(dataset_root: Path) -> dict[str, Any]:
    """Return a JSON-safe calculation payload, or an explicit unavailable payload.

    The calculation boundary is deliberately narrow: GL balances calculate
    Revenue, EBITDA and operating cost; the CFO cash-position extract supplies
    cash. Plans and the board floor are never manufactured from actuals.
    """
    root = Path(dataset_root)
    gl_path = _first_matching(root, "gl_extract", ".csv")
    coa_path = _first_matching(root, "chart_of_accounts", ".xlsx")
    cash_path = _first_matching(root, "cash_forecast", ".xlsx")
    if gl_path is None or coa_path is None:
        return _unavailable(
            "A GL extract and chart of accounts are required to derive the CEO finance actuals.",
            root,
        )

    accounts = _load_accounts(coa_path)
    gl = _load_gl(gl_path)
    if not gl:
        return _unavailable("The detected GL extract contains no usable debit/credit rows.", root)

    balances: dict[str, Decimal] = defaultdict(Decimal)
    dates: list[date] = []
    row_count = 0
    for row in gl:
        account = str(row.get("account") or "").strip()
        if not account:
            continue
        debit = _decimal(row.get("debit"))
        credit = _decimal(row.get("credit"))
        if debit is None or credit is None:
            continue
        balances[account] += debit - credit
        row_count += 1
        parsed_date = _date_value(row.get("date"))
        if parsed_date is not None:
            dates.append(parsed_date)

    revenue_accounts = _accounts_matching(balances, accounts, _is_revenue)
    cogs_accounts = _accounts_matching(balances, accounts, _is_cogs)
    operating_cost_accounts = _accounts_matching(balances, accounts, _is_operating_cost)
    if not revenue_accounts or not cogs_accounts or not operating_cost_accounts:
        return _unavailable(
            "The GL/Chart of Accounts mapping does not contain the revenue, COGS and operating-expense scopes required for EBITDA.",
            root,
        )

    revenue = sum((-balances[account] for account in revenue_accounts), Decimal())
    cogs = sum((balances[account] for account in cogs_accounts), Decimal())
    operating_cost = sum((balances[account] for account in operating_cost_accounts), Decimal())
    ebitda = revenue - cogs - operating_cost
    period = _period_label(dates)
    revenue_dynamics = _revenue_dynamics(gl, revenue_accounts, accounts)
    gl_evidence = {
        "file": _relative(gl_path, root),
        "sha256": _sha256(gl_path),
        "usable_rows": row_count,
        "period_start": min(dates).isoformat() if dates else None,
        "period_end": max(dates).isoformat() if dates else None,
        "chart_of_accounts_file": _relative(coa_path, root),
        "chart_of_accounts_sha256": _sha256(coa_path),
        "account_scopes": {
            "revenue": _scope(revenue_accounts, balances),
            "cogs": _scope(cogs_accounts, balances),
            "operating_cost": _scope(operating_cost_accounts, balances),
            "excluded_from_ebitda": {
                "rule": "Depreciation, amortization and interest are excluded from EBITDA.",
                "accounts": [
                    account for account in sorted(balances, key=_account_sort_key)
                    if _is_ebitda_exclusion(account, accounts.get(account, {}))
                ],
            },
        },
        "contributors": {
            "revenue": _contributors(revenue_accounts, balances, accounts, credit_nature=True),
            "cogs": _contributors(cogs_accounts, balances, accounts),
            "operating_cost": _contributors(operating_cost_accounts, balances, accounts),
        },
    }
    cash = _cash_position(cash_path, root)
    cash_evidence = cash.pop("evidence", {})
    components: dict[str, str | None] = {
        "revenue_actual": _number(revenue),
        "revenue_plan": None,
        "cogs_actual": _number(cogs),
        "ebitda_actual": _number(ebitda),
        "ebitda_plan": None,
        "operating_cost_actual": _number(operating_cost),
        "operating_cost_plan": None,
        "cash_balance": cash.get("value"),
        "board_floor": None,
    }
    actual_complete = {
        "revenue": True,
        "ebitda_margin": True,
        "operating_cost": True,
        "cash_vs_floor": bool(cash.get("complete")),
    }
    evidence = {
        "revenue": {
            "summary": f"{row_count:,} GL rows across {len(revenue_accounts)} scoped revenue accounts.",
            "files": [gl_evidence["file"], gl_evidence["chart_of_accounts_file"]],
            "actual_complete": True,
            "details": gl_evidence,
        },
        "ebitda_margin": {
            "summary": (
                f"Revenue ({_number(revenue)} SAR) less COGS ({_number(cogs)} SAR) "
                f"and operating cost ({_number(operating_cost)} SAR); depreciation, amortization and interest excluded."
            ),
            "files": [gl_evidence["file"], gl_evidence["chart_of_accounts_file"]],
            "actual_complete": True,
            "details": gl_evidence,
        },
        "operating_cost": {
            "summary": f"{len(operating_cost_accounts)} scoped operating-expense accounts, excluding depreciation, amortization and interest.",
            "files": [gl_evidence["file"], gl_evidence["chart_of_accounts_file"]],
            "actual_complete": True,
            "details": gl_evidence,
        },
        "cash_vs_floor": {
            "summary": str(cash.get("summary") or "No usable cash-position extract was found."),
            "files": list(cash_evidence.get("files") or []),
            "actual_complete": bool(cash.get("complete")),
            "details": cash_evidence,
        },
    }
    return {
        "authoritative": True,
        "derived_from": "deterministic_source_finance_kpi_engine",
        "reporting_period_key": period,
        "reporting_currency": "SAR",
        "computation_boundary": (
            "Actuals are calculated only from the listed uploaded source extracts. "
            "No plan or board floor is inferred when it is absent."
        ),
        "components": components,
        # Revenue movement is a period-by-period calculation from the same GL
        # rows as the headline actual.  A plan is deliberately absent unless a
        # separately governed budget role supplies one; actuals never become a
        # proxy plan.
        "trend": {"revenue": revenue_dynamics["trend"]},
        "dynamics": {"revenue": revenue_dynamics["movers"]},
        "actual_complete": actual_complete,
        "evidence": evidence,
        "source_files": sorted({item for group in evidence.values() for item in group["files"]}),
    }


def _revenue_dynamics(
    gl: Iterable[Mapping[str, Any]],
    revenue_accounts: Iterable[str],
    account_master: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    """Calculate real revenue periods and account movement from the GL.

    The comparison is period-over-period only.  It intentionally returns no
    plan series: an aligned budget must arrive through a separate governed
    source rather than being inferred from actual performance.
    """
    revenue_set = set(revenue_accounts)
    periods: dict[str, Decimal] = defaultdict(Decimal)
    account_periods: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for row in gl:
        account = str(row.get("account") or "").strip()
        current = _date_value(row.get("date"))
        if account not in revenue_set or current is None:
            continue
        debit = _decimal(row.get("debit"))
        credit = _decimal(row.get("credit"))
        if debit is None or credit is None:
            continue
        # Revenue is credit-natured, so credit less debit is the reported
        # positive contribution for the period.
        value = credit - debit
        period_key = current.strftime("%Y-%m")
        periods[period_key] += value
        account_periods[account][period_key] += value

    labels = sorted(periods)
    actual = [_number(periods[label]) for label in labels]
    movers: dict[str, list[dict[str, str]]] = {"lifting": [], "dragging": []}
    if len(labels) >= 2:
        previous, latest = labels[-2], labels[-1]
        deltas: list[tuple[str, Decimal]] = []
        for account, by_period in account_periods.items():
            delta = by_period.get(latest, Decimal()) - by_period.get(previous, Decimal())
            if delta:
                deltas.append((account, delta))
        for account, delta in sorted(deltas, key=lambda item: item[1], reverse=True)[:4]:
            if delta <= 0:
                continue
            label = str(account_master.get(account, {}).get("account_description") or f"Account {account}")
            movers["lifting"].append({"name": label, "delta": _sar_delta(delta)})
        for account, delta in sorted(deltas, key=lambda item: item[1])[:4]:
            if delta >= 0:
                continue
            label = str(account_master.get(account, {}).get("account_description") or f"Account {account}")
            movers["dragging"].append({"name": label, "delta": _sar_delta(delta)})
    return {
        "trend": {"labels": labels, "actual": actual, "plan": [], "has_plan_series": False},
        "movers": movers,
    }


def _unavailable(reason: str, root: Path) -> dict[str, Any]:
    return {
        "authoritative": False,
        "derived_from": "deterministic_source_finance_kpi_engine",
        "reason": reason,
        "source_files": [str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()][:20],
    }


def _first_matching(root: Path, name_fragment: str, suffix: str) -> Path | None:
    fragment = name_fragment.lower()
    for path in sorted(root.rglob(f"*{suffix}")):
        if fragment in path.name.lower():
            return path
    return None


def _load_accounts(path: Path) -> dict[str, dict[str, str]]:
    sheet = load_workbook(path, data_only=True, read_only=True).active
    rows = iter(sheet.values)
    headers = _headers(next(rows, ()))
    result: dict[str, dict[str, str]] = {}
    for values in rows:
        row = _row(headers, values)
        account = str(row.get("account") or "").strip()
        if account:
            result[account] = row
    return result


def _load_gl(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        headers = _headers(next(reader, ()))
        return [_row(headers, values) for values in reader]


def _cash_position(path: Path | None, root: Path) -> dict[str, Any]:
    if path is None:
        return {"value": None, "complete": False, "summary": "No CFO cash-position extract was found.", "evidence": {"files": []}}
    workbook = load_workbook(path, data_only=True, read_only=True)
    sheet = next((item for item in workbook.worksheets if _normal(item.title) == "cashposition"), None)
    if sheet is None:
        return {"value": None, "complete": False, "summary": "The CFO workbook has no Cash_Position sheet.", "evidence": {"files": [_relative(path, root)]}}
    rows = iter(sheet.values)
    headers = _headers(next(rows, ()))
    entries = [_row(headers, values) for values in rows]
    dated: dict[date, list[dict[str, Any]]] = defaultdict(list)
    accounts_seen: set[str] = set()
    for row in entries:
        current = _date_value(row.get("date"))
        account = str(row.get("account") or "").strip()
        if account:
            accounts_seen.add(account)
        if current is not None:
            dated[current].append(row)
    if not dated:
        return {"value": None, "complete": False, "summary": "The Cash_Position sheet contains no dated balances.", "evidence": {"files": [_relative(path, root)]}}
    latest = max(dated)
    latest_rows = dated[latest]
    reported: list[tuple[str, Decimal]] = []
    missing: list[str] = []
    for row in latest_rows:
        account = str(row.get("account") or "Unnamed account").strip()
        value = _decimal(row.get("balance_sar"))
        if value is None:
            missing.append(account)
        else:
            reported.append((account, value))
    missing.extend(sorted(accounts_seen - {str(row.get("account") or "").strip() for row in latest_rows if row.get("account")}))
    amount = sum((value for _account, value in reported), Decimal()) if reported else None
    complete = bool(amount is not None and not missing)
    coverage = f"{len(reported)} reported balance(s)"
    if missing:
        coverage += "; missing " + ", ".join(sorted(set(missing)))
    return {
        "value": _number(amount) if amount is not None else None,
        "complete": complete,
        "summary": f"Latest cash position on {latest.isoformat()}: {_number(amount) if amount is not None else 'no reported'} SAR from {coverage}.",
        "evidence": {
            "files": [_relative(path, root)],
            "file": _relative(path, root),
            "sha256": _sha256(path),
            "sheet": sheet.title,
            "as_of": latest.isoformat(),
            "reported_accounts": [{"account": account, "balance_sar": _number(value)} for account, value in reported],
            "missing_accounts": sorted(set(missing)),
            "complete": complete,
        },
    }


def _accounts_matching(balances: Mapping[str, Decimal], accounts: Mapping[str, Mapping[str, str]], predicate) -> list[str]:
    return [account for account in sorted(balances, key=_account_sort_key) if predicate(account, accounts.get(account, {}))]


def _is_revenue(account: str, row: Mapping[str, str]) -> bool:
    return str(row.get("type") or "").lower() == "revenue" or 4000 <= _account_number(account) < 5000


def _is_cogs(account: str, _row: Mapping[str, str]) -> bool:
    return 5000 <= _account_number(account) < 6000


def _is_ebitda_exclusion(account: str, row: Mapping[str, str]) -> bool:
    text = " ".join(str(row.get(key) or "") for key in ("account_description", "type")).lower()
    return _account_number(account) in {6500, 6510, 6620} or any(term in text for term in ("depreciation", "amortization", "interest"))


def _is_operating_cost(account: str, row: Mapping[str, str]) -> bool:
    number = _account_number(account)
    return 6000 <= number < 8000 and not _is_ebitda_exclusion(account, row)


def _scope(accounts: Iterable[str], balances: Mapping[str, Decimal]) -> dict[str, Any]:
    return {"accounts": list(accounts), "net_debit_minus_credit_sar": _number(sum((balances[item] for item in accounts), Decimal()))}


def _contributors(
    scoped_accounts: Iterable[str],
    balances: Mapping[str, Decimal],
    account_master: Mapping[str, Mapping[str, str]],
    *,
    credit_nature: bool = False,
) -> list[dict[str, Any]]:
    """Return reproducible account-level contributors for executive explanation."""
    rows: list[tuple[str, Decimal]] = []
    for account in scoped_accounts:
        value = -balances[account] if credit_nature else balances[account]
        rows.append((account, value))
    total = sum((value for _account, value in rows), Decimal())
    result: list[dict[str, Any]] = []
    for account, value in sorted(rows, key=lambda item: abs(item[1]), reverse=True):
        description = str(account_master.get(account, {}).get("account_description") or "").strip()
        result.append(
            {
                "account": account,
                "label": description or f"Account {account}",
                "value_sar": _number(value),
                "share_pct": float((value / total * 100).quantize(Decimal("0.1"))) if total else None,
            }
        )
    return result


def _headers(values: Iterable[Any]) -> dict[str, int]:
    return {_normal(value): index for index, value in enumerate(values) if value is not None}


def _row(headers: Mapping[str, int], values: Iterable[Any]) -> dict[str, Any]:
    items = tuple(values)
    aliases = {
        "account": ("account",), "account_description": ("accountdescription",), "type": ("type",),
        "date": ("date",), "debit": ("debit",), "credit": ("credit",), "balance_sar": ("balancesar",),
    }
    result: dict[str, Any] = {}
    for target, choices in aliases.items():
        index = next((headers[name] for name in choices if name in headers), None)
        result[target] = items[index] if index is not None and index < len(items) else None
    return result


def _normal(value: Any) -> str:
    return "".join(character for character in str(value or "").lower() if character.isalnum())


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool) or str(value).strip() == "":
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(value), pattern).date()
        except (TypeError, ValueError):
            continue
    return None


def _period_label(dates: list[date]) -> str:
    if not dates:
        return "selected period"
    start, end = min(dates), max(dates)
    if start.year == end.year and start.month == 1 and end.month == 6:
        return f"H1 {start.year}"
    return f"{start.isoformat()} to {end.isoformat()}"


def _number(value: Decimal | None) -> str | None:
    return None if value is None else format(value.quantize(Decimal("0.01")), "f")


def _sar_delta(value: Decimal) -> str:
    """Use a stable executive display while keeping the underlying trend exact."""
    sign = "+" if value > 0 else "-" if value < 0 else ""
    absolute = abs(value)
    if absolute >= Decimal("1000000"):
        amount = f"{(absolute / Decimal('1000000')):.1f}M"
    elif absolute >= Decimal("1000"):
        amount = f"{(absolute / Decimal('1000')):.1f}K"
    else:
        amount = f"{absolute.quantize(Decimal('1')):,.0f}"
    return f"{sign}SAR {amount}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name


def _account_number(account: str) -> int:
    try:
        return int(account)
    except (TypeError, ValueError):
        return -1


def _account_sort_key(account: str) -> tuple[int, str]:
    return (_account_number(account), str(account))
