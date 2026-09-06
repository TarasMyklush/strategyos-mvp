"""Explicit source-priority decisions for one governed comparison scope.

This is configuration, not model confidence. No policy is installed by default.
Unknown sources and competing top-ranked values require review rather than a
fallback to ingestion time or retrieval score.
"""
from typing import Literal

from pydantic import BaseModel,ConfigDict,Field,field_validator


class RequiredAssessment(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    assessment_type: Literal['validation','forecast_review']
    result: str=Field(min_length=1,max_length=80)
    rule_version: str=Field(min_length=1,max_length=160)
    scope_key: str | None=Field(default=None,max_length=160)


class PriorityDecision(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    reference_revision_id: str=Field(min_length=36,max_length=36)
    ranked_source_keys: tuple[str,...]=Field(min_length=1,max_length=100)
    required_assessment: RequiredAssessment | None
    expected_policy_version: int=Field(ge=0)
    rationale: str=Field(min_length=1,max_length=2000)

    @field_validator('ranked_source_keys')
    @classmethod
    def unique_sources(cls,keys):
        from .source_claims import IDENTIFIER_RE
        if len(set(keys))!=len(keys) or any(not IDENTIFIER_RE.fullmatch(key) for key in keys):
            raise ValueError('Source keys must be distinct stable identifiers.')
        return keys

    @field_validator('reference_revision_id')
    @classmethod
    def valid_revision(cls,value):
        from uuid import UUID
        return str(UUID(value))

    @field_validator('rationale')
    @classmethod
    def meaningful_reason(cls,value):
        if not value.strip():
            raise ValueError('An explicit priority rationale is required.')
        return value.strip()


class PriorityConflict(ValueError):
    pass


def priority_selection(members: list[dict],policy: dict,*,at) -> dict:
    """Resolve only with complete source coverage and satisfied review gates."""
    ranks={key:index for index,key in enumerate(policy['ranked_source_keys'])}
    represented={source.get('source_key') for record in members for source in record.get('sources',[])}
    if represented!=set(ranks):
        return {'status':'unresolved_source_coverage','selected_revision_ids':[]}
    requirement=policy.get('required_assessment')
    candidates=[]
    for record in members:
        sources={source.get('source_key') for source in record.get('sources',[])}
        if not sources or any(key not in ranks for key in sources):
            return {'status':'unresolved_source_coverage','selected_revision_ids':[]}
        if requirement:
            # API envelopes call this field 'type'; persisted policy names it
            # assessment_type. Keep the mapping explicit, not fuzzy.
            matching=[event for event in record.get('assessments',[])
                if event.get('type')==requirement['assessment_type']
                and all(event.get(key)==requirement.get(key) for key in ('rule_version','scope_key'))]
            from datetime import datetime
            try:
                matching=[event for event in matching if event.get('assessed_at')
                    and datetime.fromisoformat(event['assessed_at'])<=at]
                latest=max((datetime.fromisoformat(event['assessed_at']) for event in matching),default=None)
                matching=[event for event in matching if datetime.fromisoformat(event['assessed_at'])==latest]
                valid=bool(matching) and all(event.get('result')==requirement['result']
                    and (requirement['assessment_type']!='forecast_review' or bool(event.get('valid_until')))
                    and (not event.get('valid_until') or datetime.fromisoformat(event['valid_until'])>at) for event in matching)
            except (ValueError,TypeError):
                valid=False
            if not valid:
                return {'status':'required_review_missing','selected_revision_ids':[]}
        # For derived claims, every contributing source must be ranked; the
        # weakest contributing source determines priority, not the strongest.
        candidates.append((max(ranks[key] for key in sources),record))
    if not candidates:
        return {'status':'required_review_missing','selected_revision_ids':[]}
    best=min(rank for rank,_ in candidates)
    top=[record for rank,record in candidates if rank==best]
    from .claim_conflicts import annotate_conflicts
    if any(row['comparison']['requires_resolution'] for row in annotate_conflicts(top)):
        return {'status':'conflicting_top_priority','selected_revision_ids':[]}
    return {'status':'resolved_by_policy','selected_revision_ids':[row['claim_revision_id'] for row in top]}


def policies_at(cur,*,tenant_id,metric_key,at):
    cur.execute('''select id,scope_key,policy_version,ranked_source_keys,required_assessment,rationale
        from strategyos_claim_priority_policies where tenant_id=%s and metric_key=%s
        and effective_from<=%s and (effective_to is null or effective_to>%s)''',
        (tenant_id,metric_key,at,at))
    return {row[1]:{'id':str(row[0]),'version':row[2],'ranked_source_keys':row[3],
        'required_assessment':row[4],'rationale':row[5]} for row in cur.fetchall()}


def record_priority(repository,decision: PriorityDecision,*,context):
    """Record an explicit tenant-admin policy, never an LLM-emitted authority."""
    from datetime import UTC,datetime
    import json
    from .claim_store import _record
    from .source_claims import ClaimQuery,UsePurpose,stable_key
    if context.purpose!=UsePurpose.OPERATIONS or not context.roles.intersection({'tenant_admin'}):
        raise PermissionError('Tenant-admin authority is required for source-priority decisions.')
    context=repository.resolve_context(context)
    with repository._require_connection() as conn:
        repository._ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute('''select r.*,f.family_key,f.assertion_namespace,f.subject_type,f.subject_key,
                f.metric_key,f.business_unit,f.dimensions,f.period_start,f.period_end,f.scenario_key
                from strategyos_claim_revisions r join strategyos_claim_families f on f.id=r.claim_family_id
                where r.id=%s and r.tenant_id=%s''',(decision.reference_revision_id,context.tenant_id))
            row=_record(cur,cur.fetchone())
            if not row:
                raise PermissionError('Reference evidence is unavailable in this workspace.')
            row['input_revision_ids']=repository._input_revision_ids(cur,row['id'])
            row['source_occurrence_keys']=repository._occurrence_keys(cur,row['id'])
            claim=repository._hydrate_claim(row)
            repository._authorize_intake(cur,claim.draft,claim.revision_id,context)
        conn.commit()
    query=ClaimQuery(tenant_id=context.tenant_id,metric_key=claim.draft.metric_key,
        purpose=context.purpose,as_of_at=datetime.now(UTC),allowed_claim_kinds=frozenset({claim.draft.claim_kind}),
        business_unit=claim.draft.business_unit,scenario_key=claim.draft.scenario_key)
    records=repository.query(query,context=context)
    reference=next((record for record in records if record['claim_revision_id']==claim.revision_id),None)
    if reference is None:
        raise ValueError('Reference must be a current, eligible claim revision.')
    scope=reference['comparison']['scope_key']
    members=[record for record in records if record['comparison']['scope_key']==scope]
    sources={source['source_key'] for record in members for source in record['sources']}
    if sources!=set(decision.ranked_source_keys):
        raise ValueError('Rank every contributing source in this authorized comparison scope, exactly once.')
    fingerprint=stable_key('source-priority-v1',context.tenant_id,scope,decision.model_dump(),context.principal_id)
    with repository._require_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('select pg_advisory_xact_lock(hashtextextended(%s,0))',(context.tenant_id+scope,))
            # Recheck all contributing source rights at the write boundary.
            for member in members:
                repository._authorize_intake(cur,claim.draft,
                    member['claim_revision_id'],context)
            cur.execute('''select id,policy_version,fingerprint from strategyos_claim_priority_policies
                where tenant_id=%s and scope_key=%s and effective_to is null for update''',(context.tenant_id,scope))
            old=cur.fetchone()
            if old and old[2]==fingerprint:
                conn.commit()
                return {'policy_id':str(old[0]),'policy_version':old[1],'created':False}
            if (old[1] if old else 0)!=decision.expected_policy_version:
                raise PriorityConflict('The priority policy changed. Inspect the current version before recording.')
            cur.execute('select clock_timestamp()')
            boundary=cur.fetchone()[0]
            version=old[1]+1 if old else 1
            if old:
                cur.execute('update strategyos_claim_priority_policies set effective_to=%s where id=%s',(boundary,old[0]))
            cur.execute('''insert into strategyos_claim_priority_policies
                (tenant_id,reference_revision_id,metric_key,scope_key,policy_version,ranked_source_keys,
                 required_assessment,rationale,recorded_by,fingerprint,effective_from)
                values(%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s) returning id''',
                (context.tenant_id,claim.revision_id,claim.draft.metric_key,scope,version,
                 json.dumps(decision.ranked_source_keys),json.dumps(decision.required_assessment.model_dump())
                 if decision.required_assessment else None,decision.rationale,context.principal_id,fingerprint,boundary))
            policy_id=str(cur.fetchone()[0])
        conn.commit()
    return {'policy_id':policy_id,'policy_version':version,'created':True}
