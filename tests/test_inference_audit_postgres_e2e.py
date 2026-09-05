import base64
import os
from types import SimpleNamespace
import uuid
import pytest
from strategyos_mvp import inference_audit as audit, access_scope, state_store


def test_encrypted_retention_budget_and_failure_records(monkeypatch):
    url=os.getenv('STRATEGYOS_POSTGRES_E2E_DATABASE_URL')
    if not url:pytest.skip('Dedicated Postgres proof endpoint required.')
    import psycopg
    from cryptography.exceptions import InvalidTag
    monkeypatch.setattr(state_store,'database_connection',lambda:(psycopg.connect(url),None))
    key=os.urandom(32)
    monkeypatch.setenv('STRATEGYOS_INFERENCE_AUDIT_KEY',base64.urlsafe_b64encode(key).decode())
    monkeypatch.setenv('STRATEGYOS_INFERENCE_AUDIT_REQUIRED','true')
    monkeypatch.setenv('STRATEGYOS_INFERENCE_DAILY_REQUESTS','2')
    tenant='audit-'+uuid.uuid4().hex
    token=access_scope.principal_scope.set({'tenant_id':tenant,'subject':'test-person','role':'executive'})
    config=SimpleNamespace(llm_provider='fixture',llm_model='model-v1')
    try:
        with audit.record(config,[{'role':'user','content':'protected business question'}],100) as result:
            result['response']='protected response'
        with pytest.raises(RuntimeError,match='provider error'):
            with audit.record(config,[{'role':'user','content':'another question'}],100):
                raise RuntimeError('provider error')
        with pytest.raises(RuntimeError,match='budget'):
            with audit.record(config,[],100):pytest.fail('Provider ran after budget exhaustion')
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT id,status,prompt_cipher FROM strategyos_inference_audit WHERE tenant_key=%s ORDER BY created_at',(tenant,))
                records=cur.fetchall()
        assert [row[1] for row in records]==['completed','failed','budget_blocked']
        identity,cipher=str(records[0][0]),bytes(records[0][2])
        assert b'protected business' not in cipher
        assert 'protected business question' in audit.reveal(cipher,key=key,tenant=tenant,identity=identity,field='prompt')
        with pytest.raises(InvalidTag):audit.reveal(cipher,key=key,tenant='other',identity=identity,field='prompt')
    finally:access_scope.principal_scope.reset(token)


def test_required_audit_blocks_unscoped_provider_execution(monkeypatch):
    monkeypatch.setenv('STRATEGYOS_INFERENCE_AUDIT_REQUIRED','true')
    token=access_scope.principal_scope.set(None)
    try:
        with pytest.raises(RuntimeError,match='authenticated inference scope'):
            with audit.record(SimpleNamespace(),[],10):pytest.fail('Unscoped provider executed')
    finally:access_scope.principal_scope.reset(token)
