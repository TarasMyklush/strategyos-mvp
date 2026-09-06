from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'strategyos_mvp' / 'static'


def test_claim_workspace_has_explicit_semantic_selectors_and_no_silent_defaults():
    html = (ROOT / 'claims.html').read_text()
    for key in ('metric_key', 'claim_kind', 'business_unit', 'scenario_key', 'as_of'):
        assert f'name="{key}"' in html
    for kind in ('actual', 'plan', 'forecast', 'assumption', 'reported_claim'):
        assert f'value="{kind}"' in html
    assert 'value="unknown"' not in html  # Quarantined, not eligible for evidence queries.


def test_claim_workspace_never_renders_untrusted_source_markup_or_cached_evidence():
    script = (ROOT / 'claims.js').read_text()
    assert 'innerHTML' not in script
    assert "cache:'no-store'" in script
    assert 'results.replaceChildren()' in script
    assert 'Public web · untrusted' in script
    assert 'Licensed external source' in script
    assert 'This is not an actual' in script
    assert 'Historical result' in script
    assert 'Historical authorized claims' in script


def test_executive_source_traceability_does_not_imply_independent_verification():
    script = (ROOT / 'executive.js').read_text()
    assert "governed_fact: 'Source-backed fact'" in script
    assert "governed_fact: 'Verified fact'" not in script
    assert 'current verified figures' not in script
    for page in ('executive.html', 'guide.html'):
        assert 'verified company data' not in (ROOT / page).read_text()


def test_unresolved_priority_explains_missing_coverage_and_review_separately():
    script = (ROOT / 'claims.js').read_text()
    assert 'unresolved_source_coverage:' in script
    assert 'required_review_missing:' in script
    assert 'snapshot_selection_not_current_at_analysis:' in script
