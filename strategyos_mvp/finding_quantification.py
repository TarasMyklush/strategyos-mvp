"""Shared review boundary for aggregate financial conclusions.

Original finding amounts remain available for review; only locked or approved
findings contribute to reviewed totals. This does not certify cash realization.
"""
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation


def reviewed(finding):
    status = finding.get('status') if isinstance(finding, Mapping) else getattr(finding, 'status', None)
    return status in {'locked', 'approved'}


def reviewed_findings(findings):
    return [finding for finding in findings if reviewed(finding)]


def reviewed_amount(finding, field='recoverable_sar'):
    if not reviewed(finding):
        return 0.0
    value = finding.get(field, 0) if isinstance(finding, Mapping) else getattr(finding, field, 0)
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('Reviewed financial amount is invalid.') from None
    if not amount.is_finite() or amount < 0:
        raise ValueError('Reviewed financial amount must be finite and nonnegative.')
    return float(amount)
