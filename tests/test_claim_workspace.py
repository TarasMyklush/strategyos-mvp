from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'strategyos_mvp' / 'static'


def test_claim_workspace_has_explicit_semantic_selectors_and_no_silent_defaults():
    html = (ROOT / 'claims.html').read_text()
    for key in ('metric_key', 'claim_kind', 'business_unit', 'scenario_key'):
        assert f'name="{key}"' in html
    for kind in ('actual', 'plan', 'forecast', 'assumption', 'reported_claim'):
        assert f'value="{kind}"' in html


def test_claim_workspace_never_renders_untrusted_source_markup_or_cached_evidence():
    script = (ROOT / 'claims.js').read_text()
    assert 'innerHTML' not in script
    assert "cache:'no-store'" in script
    assert 'results.replaceChildren()' in script
    assert 'Public web · untrusted' in script
    assert 'Licensed external source' in script
    assert 'This is not an actual' in script
