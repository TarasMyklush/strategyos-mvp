from copy import deepcopy
from decimal import Decimal
import hashlib
from types import SimpleNamespace
import pytest
from openpyxl import Workbook
from strategyos_mvp.quarterly_revenue import reconcile, answer, intent

QUESTION = "Break down this quarter's revenue by segment — which segments are growing and which are shrinking?"
BUDGET = 'What were the key movers of revenue vs budget this half — up and down, ranked by impact?'


def rows():
    keys = ('Business Unit', 'Q2 Revenue (SAR M)', 'Q2 Budget', 'H1 Revenue', 'H1 Budget')
    return [dict(zip(keys, values)) for values in [
        ('Renamed unit', 30, 20, 50, 40), ('Zero base', 5, 6, 5, 6),
        ('Shrinking', 5, 8, 20, 22), ('Eliminations', -2, -1, -4, -2),
        ('GROUP (bottom-up)', 38, 33, 71, 66)]]


def test_bridge_reconciles_periods_eliminations_zero_base_and_row_order():
    result = reconcile(rows())
    assert result['group']['quarter_change'] == 5
    assert result['group']['budget_change'] == 5
    assert result['units'][0]['quarter_growth_pct'] == 50
    assert result['units'][1]['quarter_growth_pct'] is None
    assert result['units'][2]['quarter_growth_pct'] < 0
    reordered = reconcile(list(reversed(rows())))
    assert reordered['group'] == result['group']
    assert sorted(reordered['units'],key=lambda row:row['name']) == sorted(result['units'],key=lambda row:row['name'])
    bad = deepcopy(rows()); bad[-1]['H1 Revenue'] += 1
    with pytest.raises(ValueError, match='reconcile'): reconcile(bad)
    with pytest.raises(ValueError, match='duplicate'): reconcile(rows()+[rows()[0]])
    with pytest.raises(ValueError, match='Complete'): reconcile(rows()[:-1])
    bad = deepcopy(rows()); bad[0]['H1 Revenue'] = 'NaN'
    with pytest.raises(ValueError): reconcile(bad)


def test_answer_uses_changed_year_and_verified_complete_workbook(tmp_path):
    source = 'Q2_2029_Group_Flash_Results.xlsx'
    book=Workbook(); book.active.title='RenamedTable'; book.active.append(list(rows()[0]))
    for row in rows(): book.active.append(list(row.values()))
    path=tmp_path/source; book.save(path)
    bundle=SimpleNamespace(evidence=SimpleNamespace(dataset_root=tmp_path, manifest={source:{'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}}))
    result=answer(QUESTION,bundle)
    assert result['matched'] and 'Q2 2029' in result['answer']
    assert 'Renamed unit' in result['answer'] and 'percentage unavailable' in result['answer']
    assert result['value']['group']['quarter_change']=='5'
    assert result['citations'][0]['locator']=='RenamedTable!Excel rows 2-6'
    assert 'SAR +5.00M' in answer(BUDGET,bundle)['answer']
    book.active['B2']=99;book.save(path)
    assert answer(QUESTION,bundle)['matched'] is False
    assert intent(QUESTION+' Also forecast 2030.') is None
    assert intent('What is group margin?') is None
