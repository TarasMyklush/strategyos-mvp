"""Transaction-local provenance loading for leaf claims already selected by policy scope.

Calculated claims retain the recursive validation path. No result is cached
between requests, tenants, source-policy changes or analysis timestamps.
"""
from datetime import datetime, UTC
from .source_claims import ClaimAssessment, SourceAccessPolicy


def assessment(item):
    return ClaimAssessment(claim_revision_id=str(item['claim_revision_id']),
        assessment_type=item['assessment_type'],result=item['result'],rule_version=item['rule_version'],
        assessed_by=item['assessed_by'],assessed_at=item['assessed_at'],reasons=tuple(item.get('reasons') or []),
        scope_key=item.get('scope_key'),valid_until=item.get('valid_until'))


def source_detail(item):
    result={key:item.get(key) for key in ('source_key','registration_version','display_name','origin_category',
        'capture_method','provider_name','license_policy_ref','sensitivity_class','retention_class',
        'author_identity','original_uri','source_native_id','source_native_version')}
    result.update(published_at=item['published_at'].isoformat() if item.get('published_at') else None,
        received_at=item['received_at'].isoformat(),locator=item.get('source_locator'))
    return result


def policy(item):
    return SourceAccessPolicy(source_key=item['source_key'],allowed_roles=frozenset(item['allowed_roles']),
        allowed_purposes=frozenset(item['allowed_purposes']),
        allowed_business_units=frozenset(item.get('allowed_business_units') or []),
        **{key:bool(item[key]) for key in ('export_allowed','external_model_allowed','quote_allowed','storage_allowed','index_allowed')})


def load_leaf_batch(cur, rows, *, tenant_id, as_of_at):
    from .claim_store import _record
    ids=[str(row['id']) for row in rows if str(row.get('claim_kind'))!='unknown']
    if not ids:
        return {}
    cur.execute('''select r.id, not exists (select 1 from strategyos_claim_revisions newer
        where newer.claim_family_id=r.claim_family_id and newer.revision_number>r.revision_number
        and newer.recorded_at<=%s) as current
        from strategyos_claim_revisions r where r.id=any(%s::uuid[]) and r.tenant_id=%s
        and not exists (select 1 from strategyos_claim_dependencies d where d.derived_claim_revision_id=r.id)''',
        (datetime.now(UTC),ids,tenant_id))
    batch={str(row[0]):{'current':bool(row[1]),'occurrences':[],'assessments':[],
        'sources':{},'policies':[],'missing':[]} for row in cur.fetchall()}
    ids=list(batch)
    if not ids:
        return batch
    cur.execute('''select claim_revision_id,assessment_type,result,rule_version,assessed_by,assessed_at,
        reasons,scope_key,valid_until from strategyos_claim_assessments where claim_revision_id=any(%s::uuid[])
        and (assessed_at<=%s or assessment_type='lifecycle'
          or (assessment_type='validation' and result in ('failed','invalid'))) order by assessed_at''', (ids,as_of_at))
    for row in cur.fetchall():
        item=_record(cur,row)
        batch[str(item['claim_revision_id'])]['assessments'].append(assessment(item))
    cur.execute('''select cel.claim_revision_id, eo.occurrence_key, ss.source_key,
        coalesce(sr.display_name,'Source registration unavailable at this analysis time') as display_name,
        coalesce(sr.origin_category,'unknown') as origin_category,
        coalesce(sr.capture_method,'unknown') as capture_method,sr.provider_name,sr.license_policy_ref,
        sr.sensitivity_class,sr.retention_class,sr.registration_version,eo.author_identity,
        eo.published_at,eo.received_at,eo.original_uri,eo.source_native_id,eo.source_native_version,
        coalesce(cel.source_locator,eo.source_locator) as source_locator
        from strategyos_claim_evidence_links cel
        join strategyos_evidence_occurrences eo on eo.id=cel.evidence_occurrence_id
        join strategyos_source_systems ss on ss.id=eo.source_system_id
        join strategyos_evidence_documents ed on ed.id=eo.evidence_document_id
        left join lateral (select v.* from strategyos_source_registration_versions v
            where v.source_system_id=ss.id and v.effective_from<=%s
            and (v.effective_to is null or v.effective_to>%s)
            order by v.registration_version desc limit 1) sr on true
        where cel.claim_revision_id=any(%s::uuid[]) order by ss.source_key,eo.occurrence_key''',
        (as_of_at,as_of_at,ids))
    for row in cur.fetchall():
        item=_record(cur,row);entry=batch[str(item['claim_revision_id'])]
        entry['occurrences'].append(str(item['occurrence_key']))
        entry['sources'][str(item['occurrence_key'])]=source_detail(item)
    cur.execute('''select distinct cel.claim_revision_id,ss.source_key,p.allowed_roles,p.allowed_purposes,
        p.allowed_business_units,p.export_allowed,p.external_model_allowed,p.quote_allowed,p.storage_allowed,p.index_allowed
        from strategyos_claim_evidence_links cel
        join strategyos_evidence_occurrences eo on eo.id=cel.evidence_occurrence_id
        join strategyos_source_systems ss on ss.id=eo.source_system_id
        left join strategyos_source_access_policies p on p.source_system_id=ss.id and p.effective_to is null
        where cel.claim_revision_id=any(%s::uuid[]) and ss.tenant_id=%s''',(ids,tenant_id))
    for row in cur.fetchall():
        item=_record(cur,row);entry=batch[str(item['claim_revision_id'])]
        if not item.get('allowed_roles') or not item.get('allowed_purposes'):
            entry['missing'].append(str(item.get('source_key') or 'unknown'))
        else:
            entry['policies'].append(policy(item))
    for entry in batch.values():
        entry['occurrences'].sort()
    return batch
