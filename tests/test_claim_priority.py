from datetime import UTC,datetime,timedelta
import pytest
from pydantic import ValidationError
from strategyos_mvp.claim_priority import PriorityDecision,priority_selection
from tests.test_claim_conflicts import record

NOW=datetime(2026,9,7,tzinfo=UTC)


def policy(**changes):
    return {'ranked_source_keys':['alpha','beta'],'required_assessment':None,**changes}


def members():
    return [record('one',sources=[{'source_key':'alpha'}]),record('two',value='12',sources=[{'source_key':'beta'}])]


def test_priority_is_explicit_and_unknown_sources_do_not_fall_through():
    assert priority_selection(members(),policy(),at=NOW)['selected_revision_ids']==['one']
    assert priority_selection(members(),policy(ranked_source_keys=['beta','alpha']),at=NOW)['selected_revision_ids']==['two']
    assert priority_selection(members(),policy(ranked_source_keys=['alpha']),at=NOW)['status']=='unresolved_source_coverage'
    rows=members();rows[1]['sources']=[{'source_key':'alpha'}]
    assert priority_selection(rows,policy(ranked_source_keys=['alpha']),at=NOW)['status']=='conflicting_top_priority'


def test_required_review_cannot_use_older_acceptance_or_missing_forecast_deadline():
    requirement={'assessment_type':'forecast_review','result':'accepted','rule_version':'1','scope_key':'board:June'}
    selected=policy(required_assessment=requirement)
    rows=members()
    assert priority_selection(rows,selected,at=NOW)['status']=='required_review_missing'
    event={'type':'forecast_review','result':'accepted','rule_version':'1','scope_key':'board:June',
        'assessed_at':(NOW-timedelta(days=2)).isoformat(),'valid_until':(NOW+timedelta(days=1)).isoformat()}
    for row in rows:row['assessments']=[event]
    assert priority_selection(rows,selected,at=NOW)['status']=='resolved_by_policy'
    rows[0]['assessments']=[{**event,'valid_until':None}]
    assert priority_selection(rows,selected,at=NOW)['status']=='required_review_missing'
    rows[0]['assessments']=[event,{**event,'result':'rejected','assessed_at':(NOW-timedelta(days=1)).isoformat()}]
    assert priority_selection(rows,selected,at=NOW)['status']=='required_review_missing'


def test_policy_payload_cannot_claim_actor_tenant_or_implicit_review_choice():
    valid={'reference_revision_id':'11111111-1111-1111-1111-111111111111',
        'ranked_source_keys':['alpha','beta'],'required_assessment':None,'expected_policy_version':0,'rationale':'Explicit source policy'}
    assert PriorityDecision(**valid)
    for extra in [{'actor':'CEO'},{'tenant_id':'foreign'},{'approved':True}]:
        with pytest.raises(ValidationError):PriorityDecision(**valid,**extra)
    with pytest.raises(ValidationError):PriorityDecision(**{key:value for key,value in valid.items() if key!='required_assessment'})


def test_review_expiry_future_events_and_tied_rejection_fail_closed():
    requirement={'assessment_type':'validation','result':'accepted','rule_version':'1','scope_key':None}
    event={'type':'validation','result':'accepted','rule_version':'1','scope_key':None,
        'assessed_at':(NOW-timedelta(days=1)).isoformat(),'valid_until':None}
    for changes in [
        {'valid_until':NOW.isoformat()},
        {'assessed_at':(NOW+timedelta(seconds=1)).isoformat()},
        {'assessed_at':'not-a-date'},
        {'assessed_at':'2026-09-06T00:00:00'},
        {'rule_version':'2'},
    ]:
        rows=members()
        for row in rows:row['assessments']=[{**event,**changes}]
        assert priority_selection(rows,policy(required_assessment=requirement),at=NOW)['selected_revision_ids']==[]
    rows=members()
    for row in rows:row['assessments']=[event,{**event,'result':'rejected'}]
    assert priority_selection(rows,policy(required_assessment=requirement),at=NOW)['status']=='required_review_missing'


def test_derived_claim_uses_weakest_contributing_source():
    rows=members()
    rows[0]['sources']=[{'source_key':'alpha'},{'source_key':'beta'}]
    # Both now have the same weakest source and disagree. A high-ranked input
    # must not launder the lower-ranked input into a preferred derived value.
    assert priority_selection(rows,policy(),at=NOW)['status']=='conflicting_top_priority'
