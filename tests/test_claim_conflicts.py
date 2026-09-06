from copy import deepcopy
from strategyos_mvp.claim_conflicts import annotate_conflicts


def record(revision='one',**changes):
    return {'claim_revision_id':revision,'subject':{'type':'enterprise','key':'group'},
        'metric_key':'qa.metric','claim_kind':'actual','business_unit':None,
        'dimensions':{},'scenario':None,'period':{'start':'2026-06-01','end':'2026-06-30'},
        'value':'10','value_type':'numeric','scale':'1','unit':'SAR','currency':'SAR',**changes}


def test_conflict_disclosure_never_chooses_latest_or_search_rank():
    rows = [record(),record('two',value='12')]
    original = deepcopy(rows)
    for ordered in [rows,list(reversed(rows))]:
        result = annotate_conflicts(ordered)
        assert all(r['comparison']['requires_resolution'] for r in result)
        assert all(r['comparison']['status']=='unresolved_conflict' for r in result)
        assert all(r['comparison']['independent_corroboration']=='not_assessed' for r in result)
    assert rows == original


def test_normalization_preserves_scale_without_claiming_independent_corroboration():
    result = annotate_conflicts([record(),record('two',value='0.01',scale='1000')])
    assert all(r['comparison']['status']=='consistent_values' for r in result)
    assert all(not r['comparison']['requires_resolution'] for r in result)


def test_different_period_kind_entity_or_scenario_is_not_a_conflict():
    for change in [{'period':{'start':'2026-01-01','end':'2026-06-30'}},
                   {'claim_kind':'forecast'},{'subject':{'type':'enterprise','key':'other'}},
                   {'scenario':'downside'},{'business_unit':'retail'}]:
        result = annotate_conflicts([record(),record('two',value='12',**change)])
        assert all(r['comparison']['status']=='single_claim' for r in result)


def test_different_units_and_text_are_not_silently_converted():
    for change in [{'currency':'USD','unit':'USD'},{'value_type':'text'}]:
        result = annotate_conflicts([record(),record('two',**change)])
        assert all(r['comparison']['requires_resolution'] for r in result)
