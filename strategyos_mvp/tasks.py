from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class TaskSpec:
    task_key: str
    label: str
    required_roles: tuple[str, ...]
    readiness_reason: str
    missing_role_labels: dict[str, str]
    partial_roles: tuple[str, ...] = ()
    requires_full_run_model: bool = False


_TASK_REGISTRY: dict[str, TaskSpec] = {}


def register_task(spec: TaskSpec) -> TaskSpec:
    existing = _TASK_REGISTRY.get(spec.task_key)
    if existing is not None and existing != spec:
        raise ValueError(f"Task '{spec.task_key}' is already registered.")
    _TASK_REGISTRY[spec.task_key] = spec
    return spec


def registered_task_specs() -> tuple[TaskSpec, ...]:
    return tuple(_TASK_REGISTRY.values())


def label_for_task(task_key: str) -> str:
    spec = _TASK_REGISTRY.get(str(task_key))
    return spec.label if spec else str(task_key)


def blocked_task_items_for_empty_source_pack() -> list[dict[str, object]]:
    return [
        _task_item(
            spec,
            status_value="blocked",
            reasons=["No supported files were staged from the selected source pack."],
            missing=["supported source files"],
        )
        for spec in registered_task_specs()
    ]


def evaluate_task_readiness_items(
    *,
    has_role: Callable[[str], bool],
    run_ready: bool,
) -> list[dict[str, object]]:
    return [
        evaluate_task_readiness(spec, has_role=has_role, run_ready=run_ready)
        for spec in registered_task_specs()
    ]


def evaluate_task_readiness(
    spec: TaskSpec,
    *,
    has_role: Callable[[str], bool],
    run_ready: bool,
) -> dict[str, object]:
    required_ready = all(has_role(role) for role in spec.required_roles)
    if spec.requires_full_run_model:
        status_value = "ready" if run_ready and required_ready else "blocked"
    elif required_ready:
        status_value = "ready"
    elif spec.partial_roles and all(has_role(role) for role in spec.partial_roles):
        status_value = "partial"
    else:
        status_value = "blocked"

    missing = [
        spec.missing_role_labels.get(role, f"classified {role} coverage")
        for role in spec.required_roles
        if not has_role(role)
    ]
    if spec.requires_full_run_model and not run_ready:
        missing.append("current run-model normalization coverage")
    return _task_item(
        spec,
        status_value=status_value,
        reasons=[spec.readiness_reason],
        missing=missing,
    )


def _task_item(
    spec: TaskSpec,
    *,
    status_value: str,
    reasons: list[str],
    missing: list[str],
) -> dict[str, object]:
    return {
        "task_key": spec.task_key,
        "label": spec.label,
        "status": status_value,
        "reasons": reasons,
        "missing": missing,
    }


register_task(
    TaskSpec(
        task_key="cash_leakage_discovery",
        label="Cash Leakage Discovery",
        required_roles=(
            "ap_ledger",
            "vendor_master",
            "gl_extract",
            "purchase_orders",
            "cash_forecast",
        ),
        partial_roles=("ap_ledger",),
        readiness_reason=(
            "Cash leakage baseline is runnable when AP, vendor, GL, PO, and "
            "cash-forecast sources are classified into the current run model."
        ),
        missing_role_labels={
            "ap_ledger": "classified AP coverage",
            "vendor_master": "classified vendor master coverage",
            "gl_extract": "classified GL coverage",
            "purchase_orders": "classified PO coverage",
            "cash_forecast": "classified cash-forecast coverage",
        },
    )
)

register_task(
    TaskSpec(
        task_key="working_capital_drift_check",
        label="Working Capital Drift Check",
        required_roles=("ap_ledger", "ar_ledger"),
        readiness_reason=(
            "Working capital drift requires classified AP and AR ledgers with "
            "invoice and settlement timing fields."
        ),
        missing_role_labels={
            "ap_ledger": "classified AP coverage",
            "ar_ledger": "classified AR coverage",
        },
    )
)

register_task(
    TaskSpec(
        task_key="drill_down_qa",
        label="Drill-Down Q&A",
        required_roles=("gl_extract", "trial_balance"),
        requires_full_run_model=True,
        readiness_reason=(
            "Drill-down Q&A becomes runnable when the current run model can "
            "execute and classify GL plus trial-balance baseline sources."
        ),
        missing_role_labels={
            "gl_extract": "classified GL coverage",
            "trial_balance": "classified trial-balance coverage",
        },
    )
)
