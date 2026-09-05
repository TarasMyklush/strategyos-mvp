"""Source-scoped listed-peer comparisons; unknown listing flags stay unknown."""
from decimal import Decimal
import json
from pathlib import PurePosixPath
import re
from .receivables_aging import _amount, _verified_workbook


def matches(question):
    text=' '.join(str(question).casefold().strip().rstrip('?.!').split())
    return bool(re.fullmatch(r"how does each bu['’]s margin compare to its listed peers",text))


def compare(rows, year):
    field=f'{year} EBITDA %'; seen=set(); own=[]; peers=[]; unknown=[]; missing=[]
    for row in rows:
        name=str(row.get('Competitor') or '').strip()
        if not name or name in seen:raise ValueError('Missing or duplicate comparator identity')
        seen.add(name)
        if re.search(r'\(us\)$',name,re.I):own.append(row);continue
        flag=str(row.get('Listed?') or '').strip().casefold()
        if flag != 'yes':unknown.append(name);continue
        try:margin=_amount(row[field])
        except (KeyError,ValueError):missing.append(name);continue
        peers.append({'name':name,'margin_pct':margin})
    if len(own)!=1:raise ValueError('A unique explicitly identified own-BU row is required')
    margin=_amount(own[0][field]);name=re.sub(r'\s*\(us\)$','',str(own[0]['Competitor']),flags=re.I)
    for peer in peers:
        peer['gap_percentage_points']=margin-peer['margin_pct']
    peers.sort(key=lambda row:(-row['margin_pct'],row['name']))
    return {'business_unit':name,'margin_pct':margin,'listed_peers':peers,'excluded_listing':sorted(unknown),'missing_peer_margin':sorted(missing)}


def answer(question,bundle):
    if not matches(question) or getattr(bundle,'evidence',None) is None:return None
    sources=[path for path in bundle.evidence.manifest if 'competitor_financials' in PurePosixPath(path).stem.casefold() and path.endswith('.xlsx')]
    if len(sources)!=1:return None
    source=sources[0]
    try:
        sheets=[(sheet,rows) for sheet,rows in _verified_workbook(bundle,source,include_row_numbers=True)
                if rows and {'Competitor','Listed?'} <= rows[0][1].keys()]
        if not sheets or len(sheets)>8:raise ValueError('A bounded complete comparator workbook is required')
        years=[{int(m[1]) for key in rows[0][1] if (m:=re.fullmatch(r'(20\d{2}) EBITDA %',str(key)))} for _,rows in sheets]
        common=set.intersection(*years)
        if not common:raise ValueError('No common margin period')
        year=max(common);results=[];citations=[]
        for sheet,numbered in sheets:
            # One exact range per sector is bounded and covers every included
            # and excluded comparator. Blank-separated tables need correction.
            if [n for n,_ in numbered] != list(range(2,numbered[-1][0]+1)):raise ValueError('Noncontiguous comparator table')
            results.append(compare([row for _,row in numbered],year))
            citations.append({'source_path':source,'source_hash':bundle.evidence.manifest[source]['sha256'],
                'locator':f'{sheet}!Excel rows 2-{numbered[-1][0]}','excerpt':'Complete sector comparator table, own-BU margin and explicit listing flags.'})
    except (ValueError,KeyError):
        return {'matched':False,'available':False,'answer':'The peer comparison requires verified, consistently dated tables with a unique own-BU row and explicit listing flags.','citations':[]}
    text=f"{year} EBITDA-margin comparison using the comparative workbook's own-BU figures and only peers explicitly marked Listed? = Yes. These are source-reported comparative figures, not a reconciliation to the separate group P&L.\n"
    for row in results:
        text+=f"{row['business_unit']}: {row['margin_pct']:.2f}%. "
        if row['listed_peers']:
            text+='; '.join(f"{peer['name']} {peer['margin_pct']:.2f}% (BU minus peer {peer['gap_percentage_points']:+.2f} percentage points)" for peer in row['listed_peers'])+'.'
        else:text+='No peer is explicitly confirmed as listed in this sector table; no listed-peer comparison can be established.'
        if row['missing_peer_margin']:text+=' Listed peers missing a margin: '+', '.join(row['missing_peer_margin'])+'.'
        text+='\n'
    text+='Rows without an explicit Yes listing flag are excluded; a blank or dash is not proof that a company is private. Group P&L reconciliation is required before using comparative-workbook margins as group actuals. No live exchange-status lookup was performed.'
    return {'matched':True,'available':True,'answer':text,'basis':'Same-period EBITDA percentages from a hash-verified comparative workbook. Percentage-point gap = own-BU margin minus peer margin. Only explicit Yes listing flags are included; missing coverage remains visible.',
            'value':json.loads(json.dumps({'year':year,'sectors':results},default=str)),'citations':citations}
