import json
from pathlib import Path
import subprocess
from strategyos_mvp.executive_presentation import _executive_kpi_brief


def test_frozen_report_preview_skips_empty_optional_artifacts():
    from strategyos_mvp.board_api import _primary_report_route
    files = {'qa.md': b'', 'manifest.json': b'{}', 'working_capital.md': b'# Approved cash analysis'}
    routes = {name: '/frozen/' + name for name in files}
    assert _primary_report_route(files, routes) == '/frozen/working_capital.md'
    assert _primary_report_route({'qa.md': b'  '}, routes) is None


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


def test_closed_board_view_never_reads_current_run(monkeypatch):
    from strategyos_mvp import api, board_memory
    monkeypatch.setattr(api,'_latest_summary',lambda: (_ for _ in ()).throw(AssertionError('live source accessed')))
    snapshot={'digest':'frozen-digest','packet':{'context':{'executive_packet':{'run_id':'original-run','board_meeting_id':'meeting-a','run_source':'immutable_board_snapshot'}}}}
    monkeypatch.setattr(board_memory,'read_meeting',lambda tenant,meeting:snapshot if tenant=='tenant-a' and meeting=='meeting-a' else None)
    principal={'tenant_id':'tenant-a','role':'executive','authenticated':True}
    result=api.latest_run(persona='board',board='closed',meeting='meeting-a',principal=principal)
    assert result['run_id']=='original-run' and result['board_snapshot_digest']=='frozen-digest'
    import pytest
    with pytest.raises(api.HTTPException) as exc:
        api.latest_run(persona='board',board='closed',meeting='missing',principal=principal)
    assert exc.value.status_code==404


def test_generic_workbook_citation_resolves_exact_sheet_row_and_detects_changes(tmp_path):
    from types import SimpleNamespace
    import hashlib
    from openpyxl import Workbook
    from strategyos_mvp.citation_resolver import resolve_manifest_workbook_row
    book=Workbook();book.active.title='Costs';book.active.append(['Component','Actual']);book.active.append(['Payroll',74.1]);path=tmp_path/'costs.xlsx';book.save(path)
    evidence=SimpleNamespace(dataset_root=tmp_path,manifest={'costs.xlsx':{'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}})
    bundle=SimpleNamespace(evidence=evidence)
    assert resolve_manifest_workbook_row(bundle,'costs.xlsx','Costs!Excel row 2')['row']['Actual']==74.1
    assert resolve_manifest_workbook_row(bundle,'costs.xlsx','Wrong!Excel row 2') is None
    assert resolve_manifest_workbook_row(bundle,'costs.xlsx','Costs!Excel row 999') is None
    assert resolve_manifest_workbook_row(bundle,'../costs.xlsx','Costs!Excel row 2') is None
    book.active['B2']=100;book.save(path)
    assert resolve_manifest_workbook_row(bundle,'costs.xlsx','Costs!Excel row 2') is None


def test_live_board_label_does_not_claim_immutable_closure():
    import subprocess
    from pathlib import Path
    source=Path('strategyos_mvp/static/executive.js').read_text()
    function=source[source.index('  function statusLabel('):source.index('  function ',source.index('  function statusLabel(')+10)]
    output=subprocess.check_output(['node','-e',function+";console.log(statusLabel('live_packet'));"],text=True)
    assert output.strip()=='Not frozen'


def test_released_board_materials_populate_existing_deck_list(monkeypatch):
    from strategyos_mvp import api
    monkeypatch.setattr(api,'_finding_rows_from_summary',lambda s:[])
    monkeypatch.setattr(api,'_latest_run_audit_summary_payload',lambda s:{})
    monkeypatch.setattr(api,'_bounded_plan_health_payload',lambda *a:{})
    monkeypatch.setattr(api,'_summary_publication_payload',lambda *a,**k:{'status':'published','publish_state':'published','publish_ready':True,'available_artifacts':[{'title':'Approved memo','artifact_key':'memo','restricted':False},{'title':'Restricted case','restricted':True}]})
    portal=api._board_portal_payload({'run_id':'a'},principal_role='executive')
    assert [item['title'] for item in portal['decks']]==['Approved memo']
    assert portal['frozen_snapshot']['status']=='live_packet'


def test_session_expiry_returns_to_login_without_treating_forbidden_as_expired():
    source=Path('strategyos_mvp/static/executive.js').read_text()
    function=source[source.index('  function fetchJson('):source.index('  function putJson(')]
    code="""const bootstrap={login_required:true};let cleared=0,redirects=[];let status=401;
const clearStoredToken=()=>cleared++;const authHeaders=()=>({});const window={location:{replace:x=>redirects.push(x)}};
const fetch=()=>Promise.resolve({status,ok:status===200,json:()=>Promise.resolve({ok:true})});
"""+function+"""(async()=>{let rejected=false;try{await fetchJson('/ui/session')}catch(e){rejected=true};status=403;let forbidden=await fetchJson('/restricted');status=200;let success=await fetchJson('/ok');console.log(JSON.stringify({rejected,cleared,redirects,forbidden,success}));})();"""
    result=json.loads(subprocess.check_output(['node','-e',code],text=True))
    assert result=={'rejected':True,'cleared':1,'redirects':['/login'],'forbidden':None,'success':{'ok':True}}
