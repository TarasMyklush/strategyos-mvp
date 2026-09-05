import hashlib
from types import SimpleNamespace
from openpyxl import Workbook
from strategyos_mvp.citation_resolver import verify_source_citations


def test_named_records_resolve_uniquely_and_changed_sources_fail(tmp_path):
    book=Workbook();sheet=book.active;sheet.title='Signals'
    sheet.append(['Signal_ID','Business Unit','Value']);sheet.append(['SIG-1','Company A',0]);sheet.append(['SIG-2','Company B',12])
    path=tmp_path/'signals.xlsx';book.save(path)
    evidence=SimpleNamespace(dataset_root=tmp_path,manifest={'signals.xlsx':{'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}})
    bundle=SimpleNamespace(evidence=evidence,ap=None,ar=None,gl=None,trial_balance=None,vendors=None,customers=None,coa=None,po=None)
    rows,errors=verify_source_citations(bundle,[{'source_path':'signals.xlsx','locator':'SIG-1'}])
    assert not errors and rows[0]['locator']=='Signals!Excel row 2' and rows[0]['resolved']
    rows,errors=verify_source_citations(bundle,[{'source_path':'signals.xlsx','locator':'Business unit / Company B'}])
    assert not errors and rows[0]['locator']=='Signals!Excel row 3'
    assert not verify_source_citations(bundle,[{'source_path':'signals.xlsx','locator':'Signals!Excel rows 2-3'}])[1]
    assert verify_source_citations(bundle,[{'source_path':'signals.xlsx','locator':'Signals!Excel rows 2-4'}])[1]
    assert verify_source_citations(bundle,[{'source_path':'signals.xlsx','locator':'SIG-999'}])[1]
    assert verify_source_citations(bundle,[{'source_path':'../signals.xlsx','locator':'Signals!Excel row 2'}])[1]
    assert verify_source_citations(bundle,[{'source_path':'signals.xlsx','locator':'SIG-1','source_hash':'invented'}])[1]
    sheet.append(['SIG-1','Company A',99]);book.save(path)
    assert verify_source_citations(bundle,[{'source_path':'signals.xlsx','locator':'SIG-1'}])[1]
    evidence.manifest['signals.xlsx']['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    assert verify_source_citations(bundle,[{'source_path':'signals.xlsx','locator':'SIG-1'}])[1]
