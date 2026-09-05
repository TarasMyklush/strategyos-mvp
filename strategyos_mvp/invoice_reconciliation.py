"""Bounded AR invoice-line reconciliation; AP coverage is never inferred."""
from collections import defaultdict
from decimal import Decimal
from .receivables_aging import _amount, _verified_workbook


def reconcile(headers, lines):
    amounts = {}; totals = defaultdict(Decimal); seen = {}
    for row in headers:
        identity = row.get('Invoice_ID')
        if not identity or identity in amounts:
            raise ValueError('Missing or duplicate header invoice ID')
        amounts[identity] = _amount(row['Amount_SAR'])
    for row in lines:
        identity = row.get('Invoice_ID'); number = row.get('Line_No')
        if not identity or number is None:
            raise ValueError('Missing invoice or line ID')
        key = (identity, number)
        if key in seen:
            raise ValueError('Duplicate invoice line ID; source correction required')
        seen[key] = True
        totals[identity] += _amount(row['Line amount (SAR)'])
    mismatches = [{'invoice_id': identity, 'header_sar': str(amount), 'lines_sar': str(totals[identity]),
                   'difference_sar': str(totals[identity] - amount)}
                  for identity, amount in amounts.items() if identity in totals and abs(totals[identity] - amount) > Decimal('0.01')]
    mismatches.sort(key=lambda row: (-abs(Decimal(row['difference_sar'])), row['invoice_id']))
    return {'header_count': len(amounts), 'covered_invoice_count': len(amounts.keys() & totals.keys()),
            'mismatches': mismatches, 'missing_lines': sorted(amounts.keys() - totals.keys()),
            'orphan_lines': sorted(totals.keys() - amounts.keys()), 'tolerance_sar': '0.01'}


def answer(question, bundle):
    from pathlib import PurePosixPath
    header = (bundle.data_contracts.get('ar_ledger') or {}).get('relative_path')
    if not header:
        return None
    # The companion file must match the current contracted extract, not a historic year.
    name = PurePosixPath(header)
    lines_source = str(name.with_name(name.name.replace('AR_Invoices_', 'AR_Invoice_Lines_', 1)))
    if lines_source == header or lines_source not in bundle.evidence.manifest:
        return None
    try:
        header_sheets = list(_verified_workbook(bundle, header))
        line_sheets = list(_verified_workbook(bundle, lines_source))
        headers = [(sheet, rows) for sheet, rows in header_sheets if rows and {'Invoice_ID', 'Amount_SAR'} <= rows[0].keys()]
        lines = [(sheet, rows) for sheet, rows in line_sheets if rows and {'Invoice_ID', 'Line_No', 'Line amount (SAR)'} <= rows[0].keys()]
        if len(headers) != 1 or len(lines) != 1:
            raise ValueError('A unique aligned header and line table is required')
        result = reconcile(headers[0][1], lines[0][1])
    except (ValueError, KeyError) as exc:
        return {'matched': False, 'answer': 'Invoice reconciliation is blocked: ' + str(exc), 'citations': [], 'available': False}
    count = len(result['mismatches'])
    text = f"The current AR extract covers {result['covered_invoice_count']} of {result['header_count']} invoice headers. Invoice exceptions exceeding SAR 0.01 between headers and summed lines: {count}."
    if count:
        text += '\nLargest exceptions (up to 10):\n' + '\n'.join(
            f"{row['invoice_id']}: header SAR {Decimal(row['header_sar']):,.2f}; lines SAR {Decimal(row['lines_sar']):,.2f}; lines minus header SAR {Decimal(row['difference_sar']):,.2f}."
            for row in result['mismatches'][:10])
    text += f"\nMissing line coverage: {len(result['missing_lines'])} headers; orphan invoice IDs in lines: {len(result['orphan_lines'])}. This reconciles the supplied VAT-inclusive AR line amounts to AR headers; AP line coverage is not supplied by this calculation."
    citations = [{'source_path': source, 'source_hash': bundle.evidence.manifest[source]['sha256'],
                  'locator': f'{sheet}!Excel rows 2-{len(rows)+1}', 'excerpt': 'Complete current AR header/line reconciliation inputs.'}
                 for source, (sheet, rows) in ((header, headers[0]), (lines_source, lines[0]))]
    return {'matched': True, 'available': True, 'answer': text, 'basis': 'Signed line amounts summed by invoice; compare with the same extract header at a SAR 0.01 tolerance. Missing, duplicate and orphan IDs remain explicit.', 'value': result, 'citations': citations}
