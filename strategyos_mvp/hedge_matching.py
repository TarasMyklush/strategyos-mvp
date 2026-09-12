"""Source-bound hedge eligibility; no default rate or best-rate selection."""
from decimal import Decimal, InvalidOperation
import re
import pandas as pd


def _decimal(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result > 0 else None
    except (InvalidOperation, ValueError):
        return None


def match_unapplied_hedges(invoices, hedges):
    required = {'Hedge_ID', 'Notional_Currency', 'Notional_Amount',
                'Locked_Rate (SAR/Foreign)', 'Trade_Date', 'Maturity_Date', 'Status'}
    if not required <= set(hedges.columns):
        return [], ['Hedge eligibility fields are missing; no counterfactual rate was inferred.']
    matches, issues = [], []
    for index, invoice in invoices.iterrows():
        if str(invoice.get('Status')).casefold() != 'paid':
            continue
        currency = str(invoice.get('Currency') or '').upper()
        if not currency or currency == 'SAR':
            continue
        reference = str(invoice.get('Invoice_ID') or '').strip()
        original = _decimal(invoice.get('Amount_Original_Currency'))
        paid = _decimal(invoice.get('Amount_SAR'))
        settlement = pd.to_datetime(invoice.get('Payment_Date'), errors='coerce', utc=True)
        if not reference or original is None or paid is None or pd.isna(settlement):
            continue
        candidates = []
        for hedge_index, hedge in hedges.iterrows():
            text = ' '.join(str(value) for value in hedge.fillna('').values)
            if not re.search(r'(?<![\w-])' + re.escape(reference) + r'(?![\w-])', text):
                continue
            status = str(hedge['Status']).casefold()
            trade = pd.to_datetime(hedge['Trade_Date'], errors='coerce', utc=True)
            maturity = pd.to_datetime(hedge['Maturity_Date'], errors='coerce', utc=True)
            rate = _decimal(hedge['Locked_Rate (SAR/Foreign)'])
            notional = _decimal(hedge['Notional_Amount'])
            if (str(hedge['Notional_Currency']).upper() != currency or
                not re.search(r'\bunapplied\b', status) or
                re.search(r'\b(closed|cancelled|canceled|settled)\b', status) or
                pd.isna(trade) or pd.isna(maturity) or not trade <= settlement <= maturity or
                rate is None or notional is None):
                continue
            candidates.append({'invoice_index': index, 'hedge_index': hedge_index,
                'hedge_id': str(hedge['Hedge_ID']), 'currency': currency,
                'rate': rate, 'notional': notional, 'foreign_amount': original,
                'paid_sar': paid, 'applied_rate': paid / original,
                'exposure_sar': paid - original * rate, 'invoice_id': reference})
        if len(candidates) > 1:
            issues.append(f'{reference}: multiple eligible hedge records require allocation review.')
        elif candidates:
            matches.append(candidates[0])
    # A shared notional is not independently reusable for every invoice.
    totals = {}
    for match in matches:
        key = match['hedge_id']
        totals[key] = totals.get(key, Decimal(0)) + match['foreign_amount']
    accepted = []
    for match in matches:
        if totals[match['hedge_id']] > match['notional']:
            issues.append(f"{match['invoice_id']}: named invoice amounts exceed hedge notional; allocation is unresolved.")
        elif match['exposure_sar'] > 0:
            accepted.append(match)
    return accepted, issues
