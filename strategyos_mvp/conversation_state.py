"""Private executive workspace state with optimistic concurrency control.

This preserves the user's view, not an authority source. Model inputs must
continue to treat conversation history as untrusted user context.
"""
import json
from typing import Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from .auth import require_role
from . import access_scope, state_store
router=APIRouter()
SCHEMA='''CREATE TABLE IF NOT EXISTS strategyos_executive_threads (
 tenant_key text NOT NULL, subject text NOT NULL, run_id uuid NOT NULL REFERENCES strategyos_runs(id),
 persona text NOT NULL, version bigint NOT NULL DEFAULT 0, threads_json jsonb NOT NULL DEFAULT '{}',
 updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(tenant_key,subject,run_id,persona))'''

class ThreadState(BaseModel):
    run_id: str
    persona: str
    version: int=Field(ge=0)
    threads: dict[str,Any]


def access(principal,run_id,persona):
    from . import api
    refusal = api._assistant_authority_refusal(api.AssistantChatRequest(question='View finance',persona=persona),principal)
    if refusal and refusal.get('response_mode') == 'authority_refusal':
        raise HTTPException(403, 'Conversation access is not permitted for this persona.')
    access_scope.guard_run(run_id,require_store=True)
    authorize_sources(principal, run_id)
    handle,failure=state_store.database_connection()
    if failure or handle is None:raise HTTPException(503,'Conversation persistence is unavailable.')
    return handle,(principal['tenant_id'],principal['subject'],run_id,persona)


def authorize_sources(principal, run_id):
    """GET and PUT require current rights; ownership alone cannot release history."""
    if principal.get('auth_disabled'):
        return
    from .claim_store import ClaimRepository
    from .source_claims import PolicyContext, UsePurpose
    if not all(principal.get(key) for key in ('tenant_id', 'subject', 'role')) or not run_id:
        raise PermissionError('Conversation source authority is unavailable.')
    try:
        result = ClaimRepository().run_source_access(run_id, context=PolicyContext(
            tenant_id=principal['tenant_id'], principal_id=principal['subject'],
            roles=frozenset({principal['role']}),
            business_units=frozenset(principal.get('business_units') or ()),
            purpose=UsePurpose.EXECUTIVE_BRIEFING))
    except (RuntimeError, ValueError, KeyError):
        raise PermissionError('Conversation source authority is unavailable.') from None
    if result.get('allowed') is not True:
        raise PermissionError('Conversation source authority is unavailable.')


@router.get('/api/conversation-state')
def read(run_id: str,persona: str,principal: dict[str,Any]=require_role('executive','bu')):
    handle,scope=access(principal,run_id,persona)
    with handle as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT version,threads_json FROM strategyos_executive_threads WHERE tenant_key=%s AND subject=%s AND run_id=%s AND persona=%s',scope)
            row=cur.fetchone()
        conn.commit()
    return {'version':row[0] if row else 0,'threads':row[1] if row else {},'persistence':'durable_private_workspace'}


@router.put('/api/conversation-state')
def write(body: ThreadState,principal: dict[str,Any]=require_role('executive','bu')):
    encoded=json.dumps(body.threads,ensure_ascii=False,allow_nan=False)
    if len(encoded.encode())>1_000_000 or len(body.threads)>100:
        raise HTTPException(413,'This conversation workspace exceeds its storage limit.')
    handle,scope=access(principal,body.run_id,body.persona)
    with handle as conn:
        with conn.cursor() as cur:
            cur.execute('INSERT INTO strategyos_executive_threads (tenant_key,subject,run_id,persona) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING',scope)
            cur.execute('''UPDATE strategyos_executive_threads SET threads_json=%s::jsonb,version=version+1,updated_at=now()
                WHERE tenant_key=%s AND subject=%s AND run_id=%s AND persona=%s AND version=%s RETURNING version''',(encoded,*scope,body.version))
            row=cur.fetchone()
            if row is None:raise HTTPException(409,'This conversation changed on another device. Refresh to load its latest state.')
        conn.commit()
    return {'version':row[0],'persistence':'durable_private_workspace'}
