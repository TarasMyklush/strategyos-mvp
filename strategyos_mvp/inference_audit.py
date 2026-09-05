"""Tenant inference reservations and encrypted, expiring diagnostic payloads."""
import base64
from contextlib import contextmanager
import hashlib
import json
import os
import time
import uuid
from . import access_scope, state_store

SCHEMA = """CREATE TABLE IF NOT EXISTS strategyos_inference_audit (
 id uuid PRIMARY KEY, tenant_key text NOT NULL, subject text NOT NULL,
 provider text NOT NULL, model text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 status text NOT NULL, reserved_units bigint NOT NULL, duration_ms integer,
 prompt_sha256 text NOT NULL, response_sha256 text, prompt_cipher bytea, response_cipher bytea,
 key_id text, payload_expires_at timestamptz NOT NULL DEFAULT now()+interval '7 days'
)"""


def required():
    return os.getenv('STRATEGYOS_INFERENCE_AUDIT_REQUIRED','false').lower()=='true'


def _key():
    raw=os.getenv('STRATEGYOS_INFERENCE_AUDIT_KEY','')
    if not raw:
        if required():raise RuntimeError('Protected inference audit is not configured. Provider call blocked.')
        return None
    try:
        key=base64.urlsafe_b64decode(raw)
        if len(key)!=32:raise ValueError()
        return key
    except Exception as exc:
        raise RuntimeError('The inference audit key is invalid. Provider call blocked.') from exc


def protect(content: str, *, key: bytes, tenant: str, identity: str, field: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce=os.urandom(12)
    aad=f'{tenant}|{identity}|{field}'.encode()
    return nonce+AESGCM(key).encrypt(nonce,content.encode(),aad)


def reveal(cipher: bytes, *, key: bytes, tenant: str, identity: str, field: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(key).decrypt(cipher[:12],cipher[12:],f'{tenant}|{identity}|{field}'.encode()).decode()


@contextmanager
def record(config, messages, max_output):
    principal=access_scope.principal_scope.get()
    if not principal or principal.get('auth_disabled'):
        if required():
            raise RuntimeError('An authenticated inference scope is required. Provider call blocked.')
        yield {}
        return
    key=_key()
    handle,failure=state_store.database_connection()
    if failure or handle is None:
        if required():raise RuntimeError('Durable inference audit is unavailable. Provider call blocked.')
        yield {}
        return
    tenant=str(principal.get('tenant_id') or '')
    identity=str(uuid.uuid4());prompt=json.dumps(messages,ensure_ascii=False,sort_keys=True)
    units=len(prompt)+int(max_output)*4  # Explicit character-equivalent reservation, never claimed as billable tokens.
    quota=max(1,int(os.getenv('STRATEGYOS_INFERENCE_DAILY_UNITS','12000000')))
    request_limit=max(1,int(os.getenv('STRATEGYOS_INFERENCE_DAILY_REQUESTS','500')))
    with handle as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(71380914)")
            cur.execute(SCHEMA)
            cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(tenant+'inference-budget',))
            cur.execute("DELETE FROM strategyos_inference_audit WHERE created_at < now()-interval '30 days'")
            cur.execute('UPDATE strategyos_inference_audit SET prompt_cipher=NULL,response_cipher=NULL WHERE payload_expires_at<now() AND (prompt_cipher IS NOT NULL OR response_cipher IS NOT NULL)')
            cur.execute("SELECT count(*),coalesce(sum(reserved_units),0) FROM strategyos_inference_audit WHERE tenant_key=%s AND created_at >= date_trunc('day',now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'",(tenant,))
            count,used=cur.fetchone();allowed=count<request_limit and used+units<=quota
            cur.execute('''INSERT INTO strategyos_inference_audit (id,tenant_key,subject,provider,model,status,reserved_units,prompt_sha256,prompt_cipher,key_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (identity,tenant,str(principal.get('subject') or ''),str(config.llm_provider),str(config.llm_model),
                 'started' if allowed else 'budget_blocked',units if allowed else 0,hashlib.sha256(prompt.encode()).hexdigest(),
                 protect(prompt,key=key,tenant=tenant,identity=identity,field='prompt') if key and allowed else None,
                 os.getenv('STRATEGYOS_INFERENCE_AUDIT_KEY_ID','v1') if key else None))
        conn.commit()
    if not allowed:raise RuntimeError('The tenant inference budget is exhausted. Provider call blocked.')
    start=time.monotonic();result={};status='failed'
    try:
        yield result
        status='completed'
    finally:
        response=str(result.get('response') or '')
        handle,failure=state_store.database_connection()
        if failure or handle is None:
            if required():raise RuntimeError('Could not finish the durable inference audit.')
        else:
            with handle as conn:
                with conn.cursor() as cur:
                    cur.execute('''UPDATE strategyos_inference_audit SET status=%s,duration_ms=%s,response_sha256=%s,response_cipher=%s
                        WHERE id=%s AND tenant_key=%s''', (status,int((time.monotonic()-start)*1000),hashlib.sha256(response.encode()).hexdigest(),
                        protect(response,key=key,tenant=tenant,identity=identity,field='response') if key and response else None,identity,tenant))
                conn.commit()
