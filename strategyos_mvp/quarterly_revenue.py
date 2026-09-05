"""Reconciled revenue bridges from a complete, hash-verified Q2 flash table."""
from decimal import Decimal
import json
from pathlib import PurePosixPath
import re
from .receivables_aging import _amount, _verified_workbook

QUARTER_PATTERN = r"break down this quarter['’]s revenue by segment\s*[—–-]\s*which segments are growing and which are shrinking"
BUDGET_PATTERN = r"what were the key movers of revenue vs budget this half\s*[—–-]\s*up and down, ranked by impact"


def intent(question):
    text = ' '.join(str(question).casefold().strip().rstrip('?.!').split())
    if re.fullmatch(QUARTER_PATTERN, text): return 'quarter'
    if re.fullmatch(BUDGET_PATTERN, text): return 'budget'
    return None


def reconcile(rows):
    required = ('Q2 Revenue (SAR M)', 'Q2 Budget', 'H1 Revenue', 'H1 Budget')
    units = []; group = None; eliminations = None; seen = set()
    for row in rows:
        name = str(row.get('Business Unit') or '').strip()
        if not name or name in seen: raise ValueError('Missing or duplicate business unit')
        seen.add(name)
        values = {key: _amount(row[key]) for key in required}
        values.update(name=name, commentary=str(row.get('Flash commentary') or ''))
        if name.casefold() == 'group (bottom-up)': group = values
        elif name.casefold() == 'eliminations': eliminations = values
        else: units.append(values)
    if not units or group is None or eliminations is None:
        raise ValueError('Complete BU, elimination and group rows are required')
    for key in required:
        if abs(sum((row[key] for row in units), Decimal(0)) + eliminations[key] - group[key]) > Decimal('.00000001'):
            raise ValueError('Business-unit rows and eliminations do not reconcile to the group')
    for row in units + [eliminations, group]:
        row['q1'] = row['H1 Revenue'] - row['Q2 Revenue (SAR M)']
        row['quarter_change'] = row['Q2 Revenue (SAR M)'] - row['q1']
        row['quarter_growth_pct'] = (row['quarter_change'] / row['q1'] * 100) if row['q1'] > 0 else None
        row['budget_change'] = row['H1 Revenue'] - row['H1 Budget']
    return {'units': units, 'eliminations': eliminations, 'group': group}


def answer(question, bundle):
    mode = intent(question)
    if mode is None or getattr(bundle, 'evidence', None) is None: return None
    sources = [path for path in bundle.evidence.manifest if re.fullmatch(r'Q2_(20\d{2})_Group_Flash_Results\.xlsx', PurePosixPath(path).name, re.I)]
    if len(sources) != 1: return None
    source = sources[0]; year = re.search(r'20\d{2}', PurePosixPath(source).name)[0]
    try:
        sheets = [(name, rows) for name, rows in _verified_workbook(bundle, source)
                  if rows and {'Business Unit', 'Q2 Revenue (SAR M)', 'Q2 Budget', 'H1 Revenue', 'H1 Budget'} <= rows[0].keys()]
        if len(sheets) != 1: raise ValueError('A unique complete flash table is required')
        sheet, rows = sheets[0]; result = reconcile(rows)
    except (ValueError, KeyError):
        return {'matched': False, 'available': False, 'answer': 'The quarterly revenue table could not be reconciled. Please review its BU, elimination and group inputs.', 'citations': []}
    group = result['group']; elimination = result['eliminations']
    if mode == 'quarter':
        text = f"Q2 {year} revenue by business unit, compared with Q1 {year} (derived as H1 minus Q2). Group revenue: SAR {group['Q2 Revenue (SAR M)']:,.2f}M; prior quarter: SAR {group['q1']:,.2f}M; movement: SAR {group['quarter_change']:+,.2f}M.\n"
        for row in sorted(result['units'], key=lambda row: (-row['quarter_change'], row['name'])):
            direction = 'growing' if row['quarter_change'] > 0 else 'shrinking' if row['quarter_change'] < 0 else 'flat'
            growth = f"{row['quarter_growth_pct']:+.2f}%" if row['quarter_growth_pct'] is not None else 'percentage unavailable because the prior-quarter base is zero or negative'
            text += f"{row['name']}: Q2 SAR {row['Q2 Revenue (SAR M)']:,.2f}M; Q1 SAR {row['q1']:,.2f}M; {direction}, SAR {row['quarter_change']:+,.2f}M ({growth}).\n"
        text += f"Consolidation eliminations: Q2 SAR {elimination['Q2 Revenue (SAR M)']:,.2f}M; Q1 SAR {elimination['q1']:,.2f}M. All BU rows plus eliminations reconcile to the reported group totals. Segments here mean business units; this is a quarter-on-quarter comparison, not year-on-year."
    else:
        text = f"H1 {year} group revenue: SAR {group['H1 Revenue']:,.2f}M actual versus SAR {group['H1 Budget']:,.2f}M budget, a SAR {group['budget_change']:+,.2f}M movement. Business-unit movements ranked by absolute impact:\n"
        for row in sorted(result['units'], key=lambda row: (-abs(row['budget_change']), row['name'])):
            text += f"{row['name']}: SAR {row['budget_change']:+,.2f}M (actual {row['H1 Revenue']:,.2f}M; budget {row['H1 Budget']:,.2f}M)."
            if row['commentary']: text += ' Source commentary: ' + row['commentary'] + '.'
            text += '\n'
        text += f"Consolidation eliminations contribute SAR {elimination['budget_change']:+,.2f}M. The complete BU bridge plus eliminations reconciles to the group movement. Source commentary is qualitative context, not a quantified causal allocation."
    return {'matched': True, 'available': True, 'answer': text,
            'basis': 'Decimal arithmetic on all source rows. H1 = Q1 + Q2; movements are actual minus comparator. Every source column reconciles across BUs and eliminations before an answer is produced. Amounts are SAR millions.',
            'value': json.loads(json.dumps(result, default=str)), 'citations': [{'source_path': source, 'source_hash': bundle.evidence.manifest[source]['sha256'],
                'locator': f'{sheet}!Excel rows 2-{len(rows)+1}', 'excerpt': 'Complete BU revenue, budget, eliminations and group reconciliation inputs.'}]}
