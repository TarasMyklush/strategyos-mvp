from types import SimpleNamespace

import pandas as pd
import pytest

from strategyos_mvp.agents.finance_agents import _compute_ebitda_baseline, _format_ebitda_citations
from strategyos_mvp.evidence import EvidenceStore


def source_bundle(tmp_path):
    accounts = [('OPS', 'Operating expenses', 'Expense', 300, 0),
                ('DEP', 'Depreciation Expense', 'Expense', 50, 0),
                ('INT', 'Interest Expense', 'Expense', 20, 0),
                ('CASH', 'Cash', 'Asset', 630, 0),
                ('SALES', 'Revenue', 'Revenue', 0, 1000)]
    coa = pd.DataFrame([(a, d, t) for a, d, t, _, _ in accounts], columns=['Account', 'Account_Description', 'Type'])
    tb = pd.DataFrame([(a, d, dr, cr) for a, d, _, dr, cr in accounts], columns=['Account', 'Account_Description', 'Debit_Total', 'Credit_Total'])
    gl = tb.rename(columns={'Debit_Total': 'Debit', 'Credit_Total': 'Credit'})
    paths = {'trial_balance': 'custom-trial.csv', 'chart_of_accounts': 'custom-accounts.csv', 'gl_extract': 'custom-ledger.csv'}
    for role, frame in [('trial_balance', tb), ('chart_of_accounts', coa), ('gl_extract', gl)]:
        frame.to_csv(tmp_path / paths[role], index=False)
    return SimpleNamespace(dataset_root=tmp_path, evidence=EvidenceStore.build(tmp_path),
        trial_balance=tb, coa=coa, gl=gl, run_metadata={'available_roles': list(paths)},
        data_contracts={role: {'relative_path': path} for role, path in paths.items()})


def test_qa_baseline_uses_verified_sources_and_account_classification_not_fixed_ids(tmp_path):
    bundle = source_bundle(tmp_path)
    result = _compute_ebitda_baseline(bundle)
    assert result['available'] and result['gl_tb_reconciled']
    assert result['revenue_sar'] == 1000
    assert result['baseline_ebitda_sar'] == 700
    assert result['baseline_margin'] == .7
    assert {c['source_path'] for c in result['citations']} == {'custom-trial.csv', 'custom-accounts.csv', 'custom-ledger.csv'}
    assert all(c['locator'] == 'rows 2–6' and c['sha256'] for c in result['citations'])
    assert 'June_2026' not in _format_ebitda_citations(result)


@pytest.mark.parametrize('defect', ['mismatch', 'unmapped', 'duplicate', 'nonfinite', 'unavailable_role', 'changed_file', 'zero_revenue'])
def test_qa_baseline_withholds_unverified_margin(tmp_path, defect):
    bundle = source_bundle(tmp_path)
    if defect == 'mismatch':
        bundle.gl.loc[0, 'Debit'] += 1
    elif defect == 'unmapped':
        bundle.gl.loc[0, 'Account'] = 'UNMAPPED'
    elif defect == 'duplicate':
        bundle.coa = pd.concat([bundle.coa, bundle.coa.iloc[:1]])
    elif defect == 'nonfinite':
        bundle.gl['Debit'] = bundle.gl['Debit'].astype(float)
        bundle.gl.loc[0, 'Debit'] = float('inf')
    elif defect == 'unavailable_role':
        bundle.run_metadata['available_roles'].remove('gl_extract')
    elif defect == 'changed_file':
        path = tmp_path / 'custom-ledger.csv'
        path.write_text(path.read_text() + '\n')
    else:
        bundle.gl.loc[4, 'Credit'] = 0
        bundle.trial_balance.loc[4, 'Credit_Total'] = 0
    result = _compute_ebitda_baseline(bundle)
    assert result['available'] is False
    assert result['reason']
    assert 'baseline_margin' not in result
