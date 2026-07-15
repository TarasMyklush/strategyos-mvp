"""Governed cost levers: what an executive could act on, derived, never invented.

An executive asking "how do I decrease operating cost?" wants a recommendation.
A model answering that question from its own knowledge produces fluent advice
about other people's jobs with nothing behind it -- the exact failure this
product exists to prevent. So a lever is a governed object, computed here from
what the run already proves, and the model's job downstream is narration only.

Three derivations, in descending order of how much they are worth:

1. Proven leakage. A finding is a lever with evidence already attached and an
   amount already reconciled -- not an opinion. These rank first because the
   money is identified, not estimated.
2. Concentration. If Salaries are 26.3% of operating cost, a 5% reduction is
   arithmetic on a number the GL proves. The lever states the line, its share,
   and what a stated reduction would yield. It does NOT assert that the line is
   too high -- nothing in the run supports that judgement.
3. The missing comparator. With no approved opex budget, no line can be called
   overspent. Saying so is honest and often the most useful answer, so absence
   is returned as a first-class item rather than silence.

Nothing here claims a line "should" be cut. The engine surfaces magnitude,
share and reconciled evidence; the decision stays with the executive.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

# A concentration lever is only worth an executive's attention if the line is
# material. Below this share the arithmetic is real but the lever is noise.
_MATERIAL_SHARE_PCT = 5.0

# The illustrative reduction applied to a concentration lever. Stated in the
# lever itself so the reader can see it is an assumption, not a target the run
# supports.
_ILLUSTRATIVE_REDUCTION_PCT = Decimal("5")


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _finding_levers(findings: Sequence[Any]) -> list[dict[str, Any]]:
    """Reconciled leakage: money already identified, with evidence attached."""
    levers: list[dict[str, Any]] = []
    for finding in findings or []:
        get = finding.get if isinstance(finding, Mapping) else lambda k, d=None: getattr(finding, k, d)
        amount = _decimal(get("recoverable_sar"))
        if not amount or amount <= 0:
            return_id = None  # noqa: F841 - explicit: a zero-value finding is not a lever
            continue
        finding_id = str(get("finding_id") or get("case_id") or "").strip()
        levers.append(
            {
                "kind": "reconciled_leakage",
                "line_item": str(get("title") or finding_id or "Governed case"),
                "current_sar": None,
                "share_pct": None,
                "addressable_sar": float(amount),
                "evidence_ref": {"finding_id": finding_id} if finding_id else {},
                "benchmark_basis": "Reconciled from the run's own findings; the amount is identified, not estimated.",
                "confidence": "reconciled",
                "owner": str(get("owner") or "").strip() or None,
            }
        )
    levers.sort(key=lambda item: item["addressable_sar"], reverse=True)
    return levers


def _concentration_levers(
    contributors: Sequence[Mapping[str, Any]],
    *,
    scope_label: str,
) -> list[dict[str, Any]]:
    """Where the spend actually sits, and what a stated reduction would yield."""
    levers: list[dict[str, Any]] = []
    for row in contributors or []:
        if not isinstance(row, Mapping):
            continue
        label = str(row.get("label") or row.get("account") or "").strip()
        # The presentation rolls the tail into "Other N accounts"; that is a
        # display device, not a line an executive can act on.
        if not label or label.casefold().startswith("other "):
            continue
        value = _decimal(row.get("value_sar"))
        share = _decimal(row.get("share_pct"))
        if value is None or value <= 0 or share is None or float(share) < _MATERIAL_SHARE_PCT:
            continue
        addressable = (value * _ILLUSTRATIVE_REDUCTION_PCT / Decimal("100")).quantize(Decimal("0.01"))
        levers.append(
            {
                "kind": "concentration",
                "line_item": label,
                "current_sar": float(value),
                "share_pct": float(share),
                "addressable_sar": float(addressable),
                "evidence_ref": {"account": str(row.get("account") or "").strip()},
                "benchmark_basis": (
                    f"{label} is {float(share):.1f}% of {scope_label}. "
                    f"A {int(_ILLUSTRATIVE_REDUCTION_PCT)}% reduction is shown to size the line; "
                    "the run holds no benchmark or budget that says this line is too high."
                ),
                "confidence": "arithmetic",
                "owner": None,
            }
        )
    levers.sort(key=lambda item: item["current_sar"] or 0, reverse=True)
    return levers


def _missing_comparators(components: Mapping[str, Any]) -> list[dict[str, Any]]:
    """What the run cannot tell you, said plainly."""
    gaps: list[dict[str, Any]] = []
    if components.get("operating_cost_plan") in (None, ""):
        gaps.append(
            {
                "kind": "missing_comparator",
                "line_item": "Approved operating-cost budget",
                "current_sar": None,
                "share_pct": None,
                "addressable_sar": None,
                "evidence_ref": {},
                "benchmark_basis": (
                    "No approved operating-cost budget is supplied for this period, so no line "
                    "can be called overspent. Supplying one turns every concentration lever below "
                    "into a variance you can hold an owner to."
                ),
                "confidence": "absent",
                "owner": None,
            }
        )
    return gaps


def derive_cost_levers(
    *,
    finance_kpi: Mapping[str, Any] | None,
    findings: Sequence[Any] | None = None,
    scope: str = "operating_cost",
    scope_label: str = "operating cost",
) -> dict[str, Any]:
    """Return the governed levers for a spend scope, or an explicit empty set.

    Every lever is traceable to a GL account or a reconciled finding. When the
    run proves nothing actionable, the result says so rather than reaching for
    the model.
    """
    payload: dict[str, Any] = {
        "scope": scope,
        "scope_label": scope_label,
        "levers": [],
        "status": "unavailable",
        "reason": "",
    }
    if not isinstance(finance_kpi, Mapping):
        payload["reason"] = f"No governed finance KPIs are available, so no {scope_label} lever can be derived."
        return payload

    components = finance_kpi.get("components") if isinstance(finance_kpi.get("components"), Mapping) else {}
    evidence = finance_kpi.get("evidence") if isinstance(finance_kpi.get("evidence"), Mapping) else {}
    scope_evidence = evidence.get(scope) if isinstance(evidence.get(scope), Mapping) else {}
    details = scope_evidence.get("details") if isinstance(scope_evidence.get("details"), Mapping) else {}
    contributors_by_scope = details.get("contributors") if isinstance(details.get("contributors"), Mapping) else {}
    contributors = list(contributors_by_scope.get(scope) or [])

    levers: list[dict[str, Any]] = []
    levers.extend(_finding_levers(findings or []))
    levers.extend(_concentration_levers(contributors, scope_label=scope_label))
    levers.extend(_missing_comparators(components))

    if not levers:
        payload["reason"] = (
            f"The run exposes no {scope_label} composition and no reconciled findings, "
            "so there is nothing to act on that this evidence supports."
        )
        return payload

    payload["levers"] = levers
    payload["status"] = "available"
    payload["total_addressable_sar"] = float(
        sum(Decimal(str(item["addressable_sar"])) for item in levers if item.get("addressable_sar"))
    )
    return payload
