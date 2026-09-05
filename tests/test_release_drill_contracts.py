import json
from pathlib import Path
import subprocess
from strategyos_mvp.executive_presentation import _executive_kpi_brief


def test_group_cost_and_margin_drill_use_consolidated_budget_basis():
    for key in ('operating_cost','ebitda_margin'):
        brief=_executive_kpi_brief({'key':key,'formula':'Legacy expense-ledger formula','inputs':[]},period='H1 2026',actual=84 if key=='operating_cost' else 16,metric='84' if key=='operating_cost' else '16%',components={'revenue_actual':100,'ebitda_actual':16,'operating_cost_actual':84},evidence={'files':['15_Budgets_Forecasts/BU_Group_Budget_2026.xlsx']},missing_inputs=[],comparison_available=True,actual_complete=True,comparison='Aligned plan',strategic_reference=None,executive_signal={})
        assert 'consolidated group revenue' in brief['calculation']['formula'].lower()
        assert 'Legacy' not in brief['calculation']['formula']
        assert len(brief['calculation']['steps'])==3
        assert brief['audit']['source_titles']==['Group and business-unit budget']
        assert not any('Less cost of goods sold'==row['label'] for row in brief['calculation']['steps'])


def test_executive_number_badges_preserve_ranges_and_scale():
    source=Path('strategyos_mvp/static/executive.js').read_text()
    function=source[source.index('  function executiveMetricTokens('):source.index('  function executiveMetricChipMarkup(')]
    code=function+"\nconsole.log(JSON.stringify(executiveMetricTokens('API prices +6-9% YoY; 74% exposure; SAR 15-20 million',3)));"
    tokens=json.loads(subprocess.check_output(['node','-e',code],text=True))
    assert tokens==['+6-9%','74%','SAR 15-20 million']


def test_ranked_cost_question_is_not_replaced_with_a_bu_commentary():
    from strategyos_mvp.api import _question_requires_analytical_result
    from strategyos_mvp.scenario_parser import _finance_bu_cost_ranking
    question='what are the three largest cost components in mizan digital health this half with actual and budget'
    assert _question_requires_analytical_result(question)
    result=_finance_bu_cost_ranking(question,{'period':'H1 2026','cost_component_source':'costs.xlsx','cost_component_rows':[
        {'business_unit':'Mizan Digital Health','component':label,'actual_sar':actual,'budget_sar':budget}
        for label,actual,budget in [('Payroll','30','25'),('COGS','90','85'),('Cloud','20','22'),('Facilities','10','9')]]})
    assert result.matched
    assert result.answer.index('COGS:') < result.answer.index('Payroll:') < result.answer.index('Cloud:')
    assert 'Facilities:' not in result.answer
    assert 'SAR 85 fixed budget' in result.answer
