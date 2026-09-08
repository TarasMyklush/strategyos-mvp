from copy import deepcopy
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from strategyos_mvp.dimensional_plan import Actuals, Plan, evaluate, fingerprint
from strategyos_mvp.plan_decomposition import (
    DecompositionRequest, HistoricalDecompositionRequest, decompose, decompose_from_history,
)

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


def price_volume_mix_bundle(bundle):
    plan, actuals, _ = bundle
    source = deepcopy(plan['cells'][0]['source'])
    plan['dimensions']['product'] = ['item-a', 'item-b']
    plan['dimensions']['region'] = ['north']
    plan['dimensions']['client'] = ['retail']
    plan['cells'] = [
        {**deepcopy(plan['cells'][0]), 'id': 'item-a', 'target': '100',
         'dimensions': {'product': 'item-a', 'region': 'north', 'client': 'retail'}},
        {**deepcopy(plan['cells'][1]), 'id': 'item-b', 'target': '200',
         'dimensions': {'product': 'item-b', 'region': 'north', 'client': 'retail'}},
    ]
    plan['metrics']['revenue']['planned_total'] = '300'
    plan['price_volume_mix_policies'] = [{
        'bridge_id': 'commercial-bridge', 'metric': 'revenue', 'mix_dimension': 'product',
        'currency_unit': 'SAR', 'price_unit': 'SAR/unit', 'volume_unit': 'unit',
        'decimal_places': 2,
        'rows': [
            {'member': 'item-a', 'cell_id': 'item-a', 'planned_price': '10', 'planned_volume': '10',
             'price_source': source, 'volume_source': source},
            {'member': 'item-b', 'cell_id': 'item-b', 'planned_price': '20', 'planned_volume': '10',
             'price_source': source, 'volume_source': source},
        ],
    }]
    actuals['observations'] = [
        {'metric': 'revenue', 'dimensions': {'product': 'item-a', 'region': 'north', 'client': 'retail'},
         'unit': 'SAR', 'value': '135', 'source': source},
        {'metric': 'revenue', 'dimensions': {'product': 'item-b', 'region': 'north', 'client': 'retail'},
         'unit': 'SAR', 'value': '198', 'source': source},
    ]
    actuals['price_volume_mix'] = [{
        'bridge_id': 'commercial-bridge', 'currency_unit': 'SAR',
        'price_unit': 'SAR/unit', 'volume_unit': 'unit',
        'rows': [
            {'member': 'item-a', 'actual_price': '9', 'actual_volume': '15',
             'price_source': source, 'volume_source': source},
            {'member': 'item-b', 'actual_price': '22', 'actual_volume': '9',
             'price_source': source, 'volume_source': source},
        ],
    }]
    return bundle


def test_price_volume_mix_reconciles_exactly_from_disclosed_units(bundle):
    result = run(price_volume_mix_bundle(bundle))
    bridge = result['price_volume_mix'][0]
    assert bridge['status'] == 'reconciled'
    assert bridge['effects'] == {
        'volume': '60.00', 'mix': '-30.00', 'price': '3.00',
        'observed_variance': '33', 'reconstructed_variance': '33.00',
    }
    assert bridge['reconciles'] is True
    finding = next(item for item in result['findings'] if item['finding_type'] == 'price_volume_mix')
    assert finding['formula_version'] == 'price-volume-mix.v1'
    assert finding['calculation_order'] == [
        'volume_at_planned_average_price', 'price_at_actual_volume',
        'mix_as_exact_reconciliation_remainder',
    ]
    assert len(finding['input_rows']) == 2


@pytest.mark.parametrize('change,match', [
    ('unit', 'units must exactly match'),
    ('members', 'members must exactly match'),
    ('actual_revenue', 'revenue cell must equal'),
    ('plan_revenue', 'target must equal'),
])
def test_price_volume_mix_fails_closed_on_inconsistent_basis(bundle, change, match):
    price_volume_mix_bundle(bundle)
    if change == 'unit': bundle[1]['price_volume_mix'][0]['price_unit'] = 'USD/unit'
    if change == 'members': bundle[1]['price_volume_mix'][0]['rows'][1]['member'] = 'item-c'
    if change == 'actual_revenue': bundle[1]['observations'][0]['value'] = '134'
    if change == 'plan_revenue': bundle[0]['price_volume_mix_policies'][0]['rows'][0]['planned_price'] = '11'
    with pytest.raises(ValueError, match=match):
        run(bundle)


def test_price_volume_mix_discloses_missing_actual_basis(bundle):
    price_volume_mix_bundle(bundle)
    bundle[1]['price_volume_mix'] = []
    result = run(bundle)
    assert result['price_volume_mix'][0]['status'] == 'missing_actual_basis'
    assert not any(item['finding_type'] == 'price_volume_mix' for item in result['findings'])


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


def decomposition_request(plan, **changes):
    source = deepcopy(plan['cells'][0]['source'])
    payload = {
        'parent_digest': fingerprint(Plan.model_validate(plan).model_dump(mode='json')),
        'parent_cell_id': 'regional',
        'split_dimension': 'client',
        'decimal_places': 2,
        'allocations': [
            {'cell_id': 'regional-hospital', 'member': 'hospital', 'weight': '1',
             'owner': 'hospital-owner', 'tolerance': '1', 'basis': source},
            {'cell_id': 'regional-pharmacy', 'member': 'pharmacy', 'weight': '2',
             'owner': 'pharmacy-owner', 'tolerance': '1', 'basis': source},
        ],
    }
    payload.update(changes)
    return DecompositionRequest.model_validate(payload)


def test_decomposition_reconciles_exactly_and_records_lineage(bundle):
    plan = Plan.model_validate(bundle[0])
    proposal = decompose(plan, decomposition_request(bundle[0]), next_version=2)
    children = {cell.id: str(cell.target) for cell in proposal.cells}
    assert children['regional-hospital'] == '33.33'
    assert children['regional-pharmacy'] == '66.67'
    assert sum(cell.target for cell in proposal.cells) == plan.metrics['revenue'].planned_total
    assert proposal.derivation.parent_version == 1
    assert proposal.derivation.remainder_rule == 'final_lexicographic_cell'
    assert proposal.derivation.allocations[0].owner == 'hospital-owner'
    assert proposal.derivation.request_hash
    # Identical input is deterministic regardless of request allocation order.
    reversed_request = decomposition_request(bundle[0])
    reversed_request.allocations.reverse()
    assert decompose(plan, reversed_request, next_version=2) == proposal


@pytest.mark.parametrize('change,match', [
    ({'parent_cell_id': 'missing'}, 'Parent cell'),
    ({'split_dimension': 'unknown'}, 'split dimension'),
])
def test_decomposition_rejects_invalid_scope_or_precision(bundle, change, match):
    request = decomposition_request(bundle[0], **change)
    with pytest.raises(ValueError, match=match):
        decompose(Plan.model_validate(bundle[0]), request, next_version=2)


def test_decomposition_rejects_precision_that_cannot_hold_parent(bundle):
    bundle[0]['cells'][0]['target'] = '100.5'
    bundle[0]['cells'][1]['target'] = '99.5'
    request = decomposition_request(bundle[0], decimal_places=0)
    with pytest.raises(ValueError, match='more decimal places'):
        decompose(Plan.model_validate(bundle[0]), request, next_version=2)


def test_decomposition_rejects_duplicate_outputs(bundle):
    request = decomposition_request(bundle[0]).model_dump(mode='json')
    request['allocations'][1]['cell_id'] = request['allocations'][0]['cell_id']
    with pytest.raises(ValueError, match='unique'):
        DecompositionRequest.model_validate(request)


def test_decomposition_lineage_cannot_disagree_with_result_cells(bundle):
    proposal = decompose(Plan.model_validate(bundle[0]), decomposition_request(bundle[0]), next_version=2)
    payload = proposal.model_dump(mode='json')
    next(cell for cell in payload['cells'] if cell['id'] == 'regional-hospital')['owner'] = 'other-owner'
    with pytest.raises(ValueError, match='differs'):
        Plan.model_validate(payload)


def historical_request(plan, **changes):
    payload = {
        'parent_digest': fingerprint(Plan.model_validate(plan).model_dump(mode='json')),
        'parent_cell_id': 'regional',
        'split_dimension': 'client',
        'historical_actual_revision': 'history-may',
        'decimal_places': 2,
        'allocations': [
            {'cell_id': 'regional-hospital', 'member': 'hospital', 'owner': 'hospital-owner',
             'tolerance': '1', 'adjustment_percent': '50'},
            {'cell_id': 'regional-pharmacy', 'member': 'pharmacy', 'owner': 'pharmacy-owner',
             'tolerance': '1', 'adjustment_percent': '0'},
        ],
    }
    payload.update(changes)
    return HistoricalDecompositionRequest.model_validate(payload)


def historical_actuals(bundle):
    source = deepcopy(bundle[0]['cells'][0]['source'])
    source['locator'] = 'historical mix rows'
    payload = {
        'schema_version': 1, 'company_id': bundle[0]['company_id'], 'kind': 'actual',
        'revision': 'history-may', 'period': {'start': '2026-05-01', 'end': '2026-05-31'},
        'recorded_on': '2026-05-31', 'observations': [
            {'metric': 'revenue', 'dimensions': {'product': 'item-a', 'region': 'north', 'client': 'hospital'},
             'unit': 'SAR', 'value': '40', 'source': source},
            {'metric': 'revenue', 'dimensions': {'product': 'item-a', 'region': 'north', 'client': 'pharmacy'},
             'unit': 'SAR', 'value': '60', 'source': source},
        ],
    }
    return payload


def test_history_decomposition_discloses_mix_adjustments_and_reconciles(bundle):
    parent = Plan.model_validate(bundle[0])
    actuals = Actuals.model_validate(historical_actuals(bundle))
    request = historical_request(bundle[0])
    proposal = decompose_from_history(parent, actuals, request, next_version=2,
                                      historical_digest='a' * 64, historical_source_pack_id='history-pack')
    children = {cell.id: str(cell.target) for cell in proposal.cells}
    assert children['regional-hospital'] == children['regional-pharmacy'] == '50.00'
    lineage = {item.member: item for item in proposal.derivation.allocations}
    assert proposal.derivation.engine_version == 'history-adjusted-allocation.v1'
    assert proposal.derivation.historical_actual_revision == 'history-may'
    assert lineage['hospital'].historical_value == Decimal('40')
    assert lineage['hospital'].adjustment_percent == Decimal('50')
    assert lineage['hospital'].effective_weight == lineage['hospital'].weight == Decimal('60')
    assert lineage['hospital'].basis != lineage['hospital'].target_source
    assert sum(cell.target for cell in proposal.cells) == Decimal('200')


@pytest.mark.parametrize('mutation,match', [
    (lambda value: value['observations'].__setitem__(0, {**value['observations'][0], 'value': None}), 'missing, not zero'),
    (lambda value: value['observations'].__setitem__(0, {**value['observations'][0], 'value': '0'}), 'must be positive'),
    (lambda value: value.update(period={'start': '2026-06-01', 'end': '2026-06-30'}, recorded_on='2026-06-30'), 'completed snapshot'),
    (lambda value: value['observations'][0].update(unit='USD'), 'unit differs'),
])
def test_history_decomposition_blocks_invalid_or_missing_history(bundle, mutation, match):
    history = historical_actuals(bundle)
    mutation(history)
    with pytest.raises(ValueError, match=match):
        decompose_from_history(Plan.model_validate(bundle[0]), Actuals.model_validate(history),
                               historical_request(bundle[0]), next_version=2,
                               historical_digest='a' * 64, historical_source_pack_id='history-pack')
