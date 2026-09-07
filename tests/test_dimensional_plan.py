from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from strategyos_mvp.dimensional_plan import Actuals, Plan, evaluate

FIXTURE = Path(__file__).parent / 'fixtures' / 'dimensional_plan'


@pytest.fixture
def bundle(tmp_path):
    shutil.copy(FIXTURE / 'evidence.csv', tmp_path)
    return (json.loads((FIXTURE / 'plan.json').read_text()),
            json.loads((FIXTURE / 'actuals.json').read_text()), tmp_path)


def run(bundle, **kwargs):
    p, a, root = bundle
    return evaluate(Plan.model_validate(p), Actuals.model_validate(a),
                    source_root=root, company_id=kwargs.get('company_id', p['company_id']),
                    as_of=kwargs.get('as_of', date(2026, 6, 30)))


def test_offset_and_evidence_survive_reordering(bundle):
    result = run(bundle)
    total = result['rollups'][0]
    assert (total['actual'], total['variance'], total['offset_detected']) == ('200', '0', True)
    assert total['behind_cells'] == ['regional']
    assert total['ahead_cells'] == ['institutional']
    assert result['comparison_basis'] == 'proposed_plan_preview'
    assert all(c['plan_source']['sha256'] and c['actual_source']['locator'] for c in result['cells'])
    bundle[0]['cells'].reverse()
    bundle[1]['observations'].reverse()
    assert run(bundle) == result


@pytest.mark.parametrize('value', [None, '0'])
def test_zero_is_measured_and_missing_blocks_total(bundle, value):
    bundle[1]['observations'][0]['value'] = value
    result = run(bundle)
    row = next(c for c in result['cells'] if c['cell_id'] == 'regional')
    assert row['actual'] == value
    total = result['rollups'][0]
    assert total['measured_cells'] == (1 if value is None else 2)
    assert total['actual'] == (None if value is None else '160')
    assert total['offset_detected'] is False


def test_unplanned_known_tuple_is_visible_not_silently_dropped(bundle):
    extra = deepcopy(bundle[1]['observations'][0])
    extra['dimensions']['client'] = 'institution'
    bundle[1]['observations'].append(extra)
    total = run(bundle)['rollups'][0]
    assert total['status'] == 'incomplete'
    assert total['actual'] is None
    assert len(total['unplanned_actuals']) == 1


@pytest.mark.parametrize('change', ['duplicate_plan', 'duplicate_actual', 'unknown_member', 'unknown_metric',
                                  'missing_dimension', 'unit', 'period', 'forecast', 'total', 'ratification',
                                  'future_actual', 'future_ratification'])
def test_invalid_imports_fail_closed(bundle, change):
    p, a, _ = bundle
    if change == 'duplicate_plan': p['cells'].append(deepcopy(p['cells'][0]))
    if change == 'duplicate_actual': a['observations'].append(deepcopy(a['observations'][0]))
    if change == 'unknown_member': a['observations'][0]['dimensions']['client'] = 'unknown'
    if change == 'unknown_metric': a['observations'][0]['metric'] = 'unknown'
    if change == 'missing_dimension': del p['cells'][0]['dimensions']['region']
    if change == 'unit': a['observations'][0]['unit'] = 'USD'
    if change == 'period': a['period']['start'] = '2026-05-01'
    if change == 'forecast': a['kind'] = 'forecast'
    if change == 'total': p['metrics']['revenue']['planned_total'] = '201'
    if change == 'ratification': p['status'] = 'ratified'
    if change == 'future_actual': a['recorded_on'] = '2026-07-01'
    if change == 'future_ratification': p['ratified_on'] = '2026-07-01'
    with pytest.raises(ValueError): run(bundle)


@pytest.mark.parametrize('value', [True, 0.1, 'NaN', 'Infinity', '1e100'])
def test_non_exact_or_nonfinite_amounts_rejected(bundle, value):
    bundle[1]['observations'][0]['value'] = value
    with pytest.raises(ValueError): run(bundle)


def test_company_and_incomplete_period_rejected(bundle):
    with pytest.raises(ValueError, match='scope'): run(bundle, company_id='another-company')
    with pytest.raises(ValueError, match='full-period'): run(bundle, as_of=date(2026, 6, 29))


@pytest.mark.parametrize('escape', ['changed', 'parent', 'absolute', 'symlink'])
def test_evidence_hash_and_root_boundary(bundle, escape):
    p, _, root = bundle
    source = p['cells'][0]['source']
    if escape == 'changed': (root / 'evidence.csv').write_text('changed')
    else:
        outside = root.parent / 'outside.csv'
        shutil.copy(root / 'evidence.csv', outside)
        if escape == 'parent': source['path'] = '../outside.csv'
        if escape == 'absolute': source['path'] = str(outside)
        if escape == 'symlink':
            (root / 'link.csv').symlink_to(outside)
            source['path'] = 'link.csv'
    with pytest.raises(ValueError): run(bundle)


def test_decimal_precision_zero_target_and_lower_is_better(bundle):
    p, a, _ = bundle
    p['cells'][0]['target'] = '0'
    p['cells'][1]['target'] = '0.2'
    p['metrics']['revenue']['planned_total'] = '0.2'
    p['metrics']['revenue']['direction'] = 'lower_is_better'
    a['observations'][0]['value'] = '0.1'
    a['observations'][1]['value'] = '0.1'
    result = run(bundle)
    assert result['rollups'][0]['actual'] == '0.2'
    zero = next(c for c in result['cells'] if c['cell_id'] == 'regional')
    assert zero['variance_percent'] is None
    assert zero['status'] == 'behind'


def test_ratification_is_imported_not_certified(bundle):
    p, _, _ = bundle
    p.update(status='ratified', ratified_by='imported-owner', ratified_on='2026-05-31',
             ratification=deepcopy(p['cells'][0]['source']))
    result = run(bundle)
    assert result['approval_status'] == 'ratified'
    assert result['approval_basis'] == 'imported_metadata_not_authorization_verified'


def test_cli_is_read_only_and_errors_have_no_partial_result(bundle):
    p, a, root = bundle
    for name, data in [('plan', p), ('actuals', a)]:
        (root / f'{name}.json').write_text(json.dumps(data))
    before = {f.name: f.read_bytes() for f in root.iterdir()}
    cmd = [sys.executable, '-m', 'strategyos_mvp.dimensional_plan', '--plan', str(root / 'plan.json'),
           '--actuals', str(root / 'actuals.json'), '--source-root', str(root),
           '--company-id', p['company_id'], '--as-of', '2026-06-30']
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)['rollups'][0]['offset_detected']
    assert before == {f.name: f.read_bytes() for f in root.iterdir()}
    cmd[-1] = '2026-06-01'
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 2
    assert proc.stdout == ''


def test_versions_sources_and_values_change_snapshot_identity(bundle):
    original = run(bundle)
    bundle[0]['version'] = 2
    revised = run(bundle)
    assert revised['analysis_hash'] != original['analysis_hash']
    assert revised['plan_hash'] != original['plan_hash']
    assert revised['actuals_hash'] == original['actuals_hash']
    bundle[1]['observations'][0]['value'] = '41'
    changed = run(bundle)
    assert changed['actuals_hash'] != revised['actuals_hash']
    assert changed['rollups'][0]['actual'] == '201'
    assert original['rollups'][0]['actual'] == '200'


def test_second_sector_uses_configuration_only(bundle):
    p, a, _ = bundle
    p['company_id'] = a['company_id'] = 'software-company'
    p['dimensions']['subscription'] = p['dimensions'].pop('product')
    for row in p['cells'] + a['observations']:
        row['dimensions']['subscription'] = row['dimensions'].pop('product')
    assert run(bundle)['rollups'][0]['offset_detected']


def test_absent_actual_and_negative_values(bundle):
    _, a, _ = bundle
    a['observations'].pop(0)
    assert run(bundle)['rollups'][0]['missing_cells'] == ['regional']
    a['observations'][0]['value'] = '-10'
    row = next(c for c in run(bundle)['cells'] if c['cell_id'] == 'institutional')
    assert row['variance'] == '-110'
    assert row['status'] == 'behind'
