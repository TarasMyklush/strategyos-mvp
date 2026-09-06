"""Explicit, bounded recalculation of registered formulas, never publication."""
from dataclasses import replace
from decimal import localcontext
import json
from uuid import NAMESPACE_URL, UUID, uuid5

from .claim_calculations import calculated_value
from .claim_store import _record
from .source_claims import ClaimQuery, UsePurpose, claim_is_eligible, stable_key


class RecalculationConflict(ValueError):
    pass


def recalculate(repository, revision_id, *, context, rationale, expected_preview=None):
    """Preview without writes; applying requires the exact preview fingerprint.

    Family locks serialize source revisions during apply. A changed input or
    policy invalidates the preview. New calculated revisions have no inherited
    review events, and no existing snapshot or approval is modified.
    """
    revision_id = str(UUID(revision_id))
    if context.purpose != UsePurpose.OPERATIONS or not context.roles.intersection({'operator','tenant_admin','system'}):
        raise PermissionError('Operator authority is required for recalculation.')
    rationale = rationale.strip()
    if not rationale or len(rationale) > 2000:
        raise ValueError('An explicit recalculation rationale is required.')
    with repository._require_connection() as conn:
        repository._ensure_schema(conn)
        with conn.cursor() as cur:
            context = replace(context,tenant_id=str(repository._tenant_uuid(cur,context.tenant_id)))
            effect_key = stable_key('recalculation-command',context.tenant_id,context.principal_id,
                revision_id,expected_preview,rationale)
            if expected_preview is not None:
                cur.execute('select pg_advisory_xact_lock(hashtextextended(%s,0))',(effect_key,))
                cur.execute('select result from strategyos_claim_recalculation_receipts where tenant_id=%s and effect_key=%s',
                    (context.tenant_id,effect_key))
                receipt = cur.fetchone()
                if receipt:
                    # A retry returns its durable result only after checking the
                    # original source authority again, never just its effect key.
                    cur.execute("""select r.*,f.family_key,f.assertion_namespace,f.subject_type,
                        f.subject_key,f.metric_key,f.business_unit,f.dimensions,f.period_start,
                        f.period_end,f.scenario_key from strategyos_claim_revisions r
                        join strategyos_claim_families f on f.id=r.claim_family_id
                        where r.id=%s and r.tenant_id=%s""",(revision_id,context.tenant_id))
                    row = _record(cur,cur.fetchone())
                    row['source_occurrence_keys'] = repository._occurrence_keys(cur,revision_id)
                    row['input_revision_ids'] = repository._input_revision_ids(cur,revision_id)
                    claim = repository._hydrate_claim(row)
                    repository._authorize_intake(cur,claim.draft,revision_id,context)
                    conn.commit()
                    return {**receipt[0],'created_count':0,'replayed':True}

            def plan():
                cur.execute('select clock_timestamp()')
                at = cur.fetchone()[0]
                nodes, active, families, policies_seen = {}, set(), set(), set()
                pending = []

                def visit(requested_id, *, root=False):
                    cur.execute("""select latest.*,f.family_key,f.assertion_namespace,f.subject_type,
                        f.subject_key,f.metric_key,f.business_unit,f.dimensions,f.period_start,
                        f.period_end,f.scenario_key from strategyos_claim_revisions requested
                        join strategyos_claim_families f on f.id=requested.claim_family_id
                        join lateral (select r.* from strategyos_claim_revisions r
                            where r.claim_family_id=f.id order by r.revision_number desc limit 1) latest on true
                        where requested.id=%s and requested.tenant_id=%s""", (requested_id,context.tenant_id))
                    raw = cur.fetchone()
                    if raw is None:
                        raise PermissionError('Calculation is unavailable in this workspace.')
                    row = _record(cur,raw)
                    family = str(row['claim_family_id'])
                    latest_id = str(row['id'])
                    if root and latest_id != revision_id:
                        raise RecalculationConflict('This calculation has a newer revision. Inspect that revision first.')
                    if family in active:
                        raise ValueError('Latest input families contain a cycle; steward review is required.')
                    if family in nodes:
                        return nodes[family]
                    families.add(family)
                    if len(families)>100 or len(active)>=32:
                        raise ValueError('Recalculation exceeds the bounded lineage limit.')
                    row['source_occurrence_keys'] = repository._occurrence_keys(cur,latest_id)
                    row['input_revision_ids'] = repository._input_revision_ids(cur,latest_id)
                    claim = repository._hydrate_claim(row)
                    draft = claim.draft
                    if root and draft.production_method != 'calculated':
                        raise ValueError('Only registered calculated claims can be recalculated.')
                    policies, missing = repository._policies_for_revision(cur,context.tenant_id,latest_id)
                    assessments = repository._assessments(cur,latest_id,as_of_at=at)
                    query = ClaimQuery(tenant_id=context.tenant_id,metric_key=draft.metric_key,
                        business_unit=draft.business_unit,scenario_key=draft.scenario_key,
                        allowed_claim_kinds=frozenset({draft.claim_kind}),purpose=context.purpose,as_of_at=at)
                    if missing or not claim_is_eligible(claim,query=query,context=context,
                            source_policies=policies,assessments=assessments).eligible:
                        raise PermissionError('Current evidence, lifecycle or source rights do not permit recalculation.')
                    cur.execute("""select p.id,p.policy_version from strategyos_source_access_policies p
                        join strategyos_source_systems s on s.id=p.source_system_id
                        where s.tenant_id=%s and s.source_key=any(%s::text[]) and p.effective_to is null""",
                        (context.tenant_id,[p.source_key for p in policies]))
                    policies_seen.update((str(row[0]),int(row[1])) for row in cur.fetchall())
                    active.add(family)
                    children = [visit(input_id) for input_id in draft.input_revision_ids]
                    if children:
                        updated = replace(draft,input_revision_ids=tuple(item['id'] for item in children))
                        with localcontext() as decimal_context:
                            decimal_context.prec = 50
                            value = calculated_value(updated,[item['row'] for item in children]) / updated.scale
                        if updated.input_revision_ids != draft.input_revision_ids or value != draft.value_numeric:
                            updated = replace(updated,value_numeric=value,metadata={**draft.metadata,
                                'recalculated_from':latest_id,'recorded_by':context.principal_id,
                                'recalculation_rationale':rationale})
                            placeholder = str(uuid5(NAMESPACE_URL,updated.fingerprint))
                            pending.append({'placeholder':placeholder,'draft':updated,'previous':claim})
                            latest_id, draft = placeholder, updated
                    active.remove(family)
                    result = {'id':latest_id,'row':{**row,'id':latest_id,
                        'value_numeric':draft.value_numeric,'scale':draft.scale},'draft':draft}
                    nodes[family] = result
                    return result

                root = visit(revision_id,root=True)
                fingerprint = stable_key('recalculation-preview',context.tenant_id,context.principal_id,
                    sorted(context.roles),sorted(context.business_units),revision_id,rationale,
                    [item['draft'].fingerprint for item in pending],sorted(policies_seen))
                return root,pending,families,fingerprint

            root,pending,families,fingerprint = plan()
            if expected_preview is not None:
                # Lock in one order, then reread. A newly introduced family makes
                # this preview obsolete instead of extending locks out of order.
                cur.execute('select id from strategyos_claim_families where id=any(%s::uuid[]) order by id for update',
                    (sorted(families),))
                cur.fetchall()
                root,pending,locked_families,fingerprint = plan()
                if locked_families != families or fingerprint != expected_preview:
                    raise RecalculationConflict('Inputs or policy changed. Preview the recalculation again.')
            proposals = {item['placeholder']:item for item in pending}
            changes = [{'metric_key':item['draft'].metric_key,'claim_kind':str(item['draft'].claim_kind),
                'previous_revision_id':item['previous'].revision_id,
                'previous_value':str(item['previous'].draft.value_numeric),
                'proposed_value':str(item['draft'].value_numeric),'unit':item['draft'].unit,
                'scale':str(item['draft'].scale),'currency':item['draft'].currency,
                'formula':item['draft'].formula_key,'formula_version':item['draft'].formula_version,
                'previous_input_revision_ids':list(item['previous'].draft.input_revision_ids),
                'proposed_inputs':[{'revision_id':key} if key not in proposals else {
                    'proposed_metric':proposals[key]['draft'].metric_key,
                    'recalculates_revision':proposals[key]['previous'].revision_id}
                    for key in item['draft'].input_revision_ids]}
                for item in pending]
            created, resolved = [], {}
            if expected_preview is not None:
                for item in pending:
                    draft = replace(item['draft'],input_revision_ids=tuple(resolved.get(key,key) for key in item['draft'].input_revision_ids))
                    receipt = repository._write_claim(cur,draft,traceability='present',
                        evidence_relationship='supports',context=context)
                    resolved[item['placeholder']] = receipt['claim_revision_id']
                    created.append(receipt)
                for change,item in zip(changes,pending):
                    change['recorded_revision_id'] = resolved[item['placeholder']]
            result = {'status':('recorded' if pending else 'unchanged') if expected_preview is not None else 'preview',
                'preview_key':fingerprint,'changes':changes,'created_count':sum(bool(r['created']) for r in created),
                'claim_revision_id':resolved.get(root['id'],root['id']) if expected_preview is not None else None,
                'review_status':'unreviewed' if pending else 'unchanged','snapshot_changed':False,'outbound_delivery':False,
                'query':{'metric_key':root['draft'].metric_key,'claim_kind':str(root['draft'].claim_kind),
                    'business_unit':root['draft'].business_unit,'scenario_key':root['draft'].scenario_key,
                    'purpose':str(context.purpose)}}
            if expected_preview is not None:
                cur.execute("""insert into strategyos_claim_recalculation_receipts
                    (tenant_id,source_claim_revision_id,effect_key,preview_key,recorded_by,rationale,result)
                    values (%s,%s,%s,%s,%s,%s,%s::jsonb)""",(context.tenant_id,revision_id,effect_key,
                        fingerprint,context.principal_id,rationale,json.dumps(result)))
        if expected_preview is not None:
            conn.commit()
        else:
            conn.rollback()
    return result
