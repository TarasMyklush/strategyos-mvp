import hashlib
import json
from types import SimpleNamespace
import pytest
from openpyxl import Workbook
from strategyos_mvp import semantic_embeddings, source_search, vector_store


def test_source_rows_preserve_zero_exact_location_and_detect_file_mutation(tmp_path):
    book=Workbook();book.active.title='Budget';book.active.append(['BU','Actual']);book.active.append(['A',0])
    path=tmp_path/'budget.xlsx';book.save(path)
    evidence=SimpleNamespace(dataset_root=tmp_path,manifest={'budget.xlsx':{'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}},pdf_text={})
    rows=list(source_search.source_records(evidence))
    assert rows[0][2:] == ('Budget!Excel row 2','BU: A; Actual: 0')
    book.active['B2']=999;book.save(path)
    with pytest.raises(ValueError,match='changed'):
        list(source_search.source_records(evidence))


def test_dense_search_sends_scope_filter_and_query_embedding(monkeypatch):
    calls=[]
    monkeypatch.setattr(semantic_embeddings,'configured',lambda:True)
    monkeypatch.setattr(vector_store,'_ensure_collection',lambda *args:None)
    monkeypatch.setattr(vector_store,'_embed_text',lambda text,query: [1.0] if query else (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(vector_store,'_qdrant_request',lambda method,path,payload: calls.append((method,path,payload)) or {'result':[]})
    scope={'must':[{'key':'tenant_slug','match':{'value':'tenant-a'}},{'key':'run_id','match':{'value':'run-a'}}]}
    vector_store._search_collection(vector_store.COLLECTION_NAME,query='المورد',filter_payload=scope,limit=3,create=True)
    assert calls[0][2]['filter']==scope
    assert calls[0][2]['vector']==[1.0]
    assert calls[0][1].endswith('/points/search')


def test_configured_semantic_status_never_substitutes_legacy_index(monkeypatch):
    monkeypatch.setattr(vector_store,'CONFIG',SimpleNamespace(qdrant_url='http://example'))
    monkeypatch.setattr(semantic_embeddings,'configured',lambda:True)
    calls=[]
    monkeypatch.setattr(vector_store,'_vector_status_for_collection',lambda run,collection,create: calls.append(collection) or {'status':'empty'})
    assert vector_store.vector_status_for_run('run-a')['status']=='empty'
    assert calls==[vector_store.COLLECTION_NAME]


def test_missing_model_manifest_fails_without_runtime_download(tmp_path,monkeypatch):
    monkeypatch.setenv('STRATEGYOS_EMBEDDING_MODEL_PATH',str(tmp_path))
    semantic_embeddings.model.cache_clear()
    with pytest.raises(FileNotFoundError):semantic_embeddings.model()
    (tmp_path/'model-manifest.json').write_text(json.dumps({'model_name':'wrong','revision':'wrong'}))
    with pytest.raises(RuntimeError,match='identity'):semantic_embeddings.model()
    semantic_embeddings.model.cache_clear()
