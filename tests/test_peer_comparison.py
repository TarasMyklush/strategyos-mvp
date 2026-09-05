from decimal import Decimal
from types import SimpleNamespace
import hashlib
import pytest
from openpyxl import Workbook
from strategyos_mvp.peer_comparison import answer,compare,matches


def rows():
    return [
        {'Competitor':'Renamed unit (us)','2031 EBITDA %':0,'Listed?':'Private'},
        {'Competitor':'Confirmed','2031 EBITDA %':4.5,'Listed?':'Yes'},
        {'Competitor':'Unknown','2031 EBITDA %':99,'Listed?':'—'},
        {'Competitor':'Private comparator','2031 EBITDA %':8,'Listed?':'Private'},
        {'Competitor':'Missing margin','2031 EBITDA %':None,'Listed?':'Yes'},
    ]


def test_explicit_listing_zero_margin_and_missing_peer_values():
    result=compare(rows(),2031)
    assert result['business_unit']=='Renamed unit' and result['margin_pct']==0
    assert result['listed_peers']==[{'name':'Confirmed','margin_pct':Decimal('4.5'),'gap_percentage_points':Decimal('-4.5')}]
    assert result['missing_peer_margin']==['Missing margin']
    assert result['excluded_listing']==['Private comparator','Unknown']
    assert compare(list(reversed(rows())),2031)==result
    with pytest.raises(ValueError,match='duplicate'):compare(rows()+[rows()[0]],2031)
    with pytest.raises(ValueError,match='unique'):compare(rows()[1:],2031)


def test_hash_verified_multi_sector_answer_preserves_missing_listing_scope(tmp_path):
    p=tmp_path/'Client_Competitor_Financials.xlsx';b=Workbook();b.active.title='First'
    for s in [b.active,b.create_sheet('Second')]:
        s.append(['Competitor','2031 EBITDA %','Listed?'])
        for row in rows():s.append(list(row.values()))
    b.save(p);bundle=SimpleNamespace(evidence=SimpleNamespace(dataset_root=tmp_path,manifest={p.name:{'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}}))
    q="How does each BU's margin compare to its listed peers?"
    result=answer(q,bundle)
    assert result['matched'] and result['value']['year']==2031
    assert len(result['citations'])==2 and '-4.50 percentage points' in result['answer']
    assert 'Unknown 99' not in result['answer'] and 'Missing margin' in result['answer']
    from strategyos_mvp.citation_resolver import verify_source_citations
    verified,errors=verify_source_citations(bundle,result['citations'])
    assert not errors and all(c['resolved'] for c in verified)
    b.active['B2']=15;b.save(p)
    assert answer(q,bundle)['matched'] is False
    assert not matches(q+' Also forecast next year.')
