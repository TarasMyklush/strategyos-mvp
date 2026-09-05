"""Versioned, deterministic metric semantics independent of client KPI identifiers."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
import re
from typing import Any, Mapping


def finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        result = float(value)
    else:
        match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", str(value))
        if not match:
            return None
        try:
            result = float(Decimal(match.group().replace(",", "")))
        except (InvalidOperation, OverflowError):
            return None
    return result if math.isfinite(result) else None


@dataclass(frozen=True)
class MetricDefinition:
    direction: str = "higher_is_better"
    weight: float = 1.0
    tolerance: float = 0.0
    version: int = 1
    unit: str = ""
    cadence: str = "monthly"
    actual_field: str = "actual"
    checkpoint_field: str = "checkpoint"
    quality: str | None = None
    finance_binding: str | None = None
    finance_scale: float = 1.0

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MetricDefinition":
        direction = str(value.get("direction", "higher_is_better")).lower().replace("-", "_")
        if direction not in {"higher_is_better", "lower_is_better"}:
            raise ValueError("Metric direction must be explicitly higher_is_better or lower_is_better")
        weight = finite_number(value.get("weight", 1))
        tolerance = finite_number(value.get("tolerance", 0))
        scale = finite_number(value.get("finance_scale", 1))
        if weight is None or weight <= 0 or tolerance is None or tolerance < 0 or scale is None or scale <= 0:
            raise ValueError("Metric weights/scales must be positive and tolerance nonnegative")
        quality = value.get("measurement_status")
        if quality not in {None, "live", "estimated", "missing"}:
            raise ValueError("Unsupported measurement status")
        return cls(direction=direction, weight=weight, tolerance=tolerance,
                   version=int(value.get("version", 1)), unit=str(value.get("unit", "")),
                   cadence=str(value.get("cadence", "monthly")),
                   actual_field=str(value.get("actual_field", "actual")),
                   checkpoint_field=str(value.get("checkpoint_field", "checkpoint")),
                   quality=quality, finance_binding=value.get("finance_binding"), finance_scale=scale)

    def attainment(self, actual: Any, checkpoint: Any) -> float | None:
        actual, checkpoint = finite_number(actual), finite_number(checkpoint)
        if actual is None or checkpoint is None or actual < 0 or checkpoint < 0:
            return None
        if self.direction == "lower_is_better":
            # A zero limit allows zero only; exceeding a zero limit is 0% attainment.
            # A zero actual meets a positive limit and receives the bounded 120% cap.
            if checkpoint == 0:
                return 1.0 if actual == 0 else 0.0
            return 1.2 if actual == 0 else min(1.2, checkpoint / actual)
        if checkpoint == 0:
            return None  # Growth relative to a zero plan has no defined ratio.
        return max(0.0, min(1.2, actual / checkpoint))

    def status(self, actual: Any, checkpoint: Any) -> str:
        actual, checkpoint = finite_number(actual), finite_number(checkpoint)
        if self.attainment(actual, checkpoint) is None:
            return "UNAVAILABLE"
        delta = actual - checkpoint
        if self.direction == "lower_is_better":
            delta = -delta
        return "BEHIND" if delta < -self.tolerance else "AHEAD" if delta > self.tolerance else "ON"


def measurement_status(value: Any, explicit: str | None = None) -> str:
    if finite_number(value) is None or explicit == "missing":
        return "missing"
    if explicit in {"live", "estimated"}:
        return explicit
    return "estimated" if re.search(r"\best(?:imated)?\b", str(value), re.I) else "live"
