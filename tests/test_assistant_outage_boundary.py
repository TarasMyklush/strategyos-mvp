"""Browser transport failures cannot certify cached company figures."""
from pathlib import Path
import subprocess


def test_authentication_and_transport_failures_never_relabel_cached_kpis_as_facts():
    source = Path('strategyos_mvp/static/executive.js').read_text()
    reply = source[source.index('  async function buildAssistantReply('):source.index('  function threadStore(')]
    failure = source[source.index('  function assistantFailureCopy('):source.index('  function applyAssistantResultToMessage(')]
    program = '''
const assert = require('node:assert/strict');
const firstDefined=(...xs)=>xs.find(x=>x!==undefined && x!==null && x!=='');
const safeArray=x=>Array.isArray(x)?x:[];
const state={activePersona:'ceo',activeDriverKey:'cash'};
const cached={key:'cash',metric:'SAR 999M',kpi_contract:{},executive_brief:{metric:'SAR 999M'}};
const getActiveDriver=()=>cached, getVisibleDrivers=()=>[cached];
const assistantEntrypointContext=()=>({kpi_key:'cash'});
const assistantThreadHistory=()=>[],activeRunId=()=> 'run-1';
const logAssistantTransportFailure=()=>{};
let error;
const postJson=async()=>{throw error;};
''' + failure + reply + '''
(async()=>{
  for(const status of [401,403,503,0]) {
    error=Object.assign(new Error('synthetic outage'),{status});
    const result=await buildAssistantReply('my cash?');
    assert.equal(result.ok,false);
    assert.equal(result.statusCode,status);
    assert.equal(result.responsePayload,undefined);
    assert(!result.answer.includes('999'));
    assert.equal(result.retryable,status!==401 && status!==403);
  }
})().catch(e=>{console.error(e);process.exit(1);});
'''
    subprocess.run(['node', '-e', program], check=True, capture_output=True, text=True)


def test_saved_client_fallbacks_lose_fact_status_and_preserve_the_question():
    source = Path('strategyos_mvp/static/executive.js').read_text()
    function = source[source.index('  function markThreadTransportFailuresRetryable('):source.index('  function logAssistantTransportFailure(')]
    program = '''
const assert=require('node:assert/strict');
const safeArray=x=>Array.isArray(x)?x:[];
const firstDefined=(...xs)=>xs.find(x=>x!==undefined && x!==null && x!=='');
const isLegacyAssistantTransportFallback=()=>false;
const inferRetryPrompt=(messages,i)=>messages[i-1].text;
const recalcThreadPreview=()=>{};
''' + function + '''
const thread={messages:[{role:'user',text:'What is my EBITDA?'},
 {role:'assistant',text:'617 million',status:'ok',payload:{language_layer_unavailable:true,determinism_tier:'governed_fact'}}]};
assert(markThreadTransportFailuresRetryable(thread));
assert.equal(thread.messages[1].status,'failed');
assert.equal(thread.messages[1].payload,undefined);
assert.equal(thread.messages[1].retryPrompt,'What is my EBITDA?');
assert(!thread.messages[1].text.includes('617'));
'''
    subprocess.run(['node', '-e', program], check=True, capture_output=True, text=True)


def test_kpi_selection_commits_composer_context_before_the_next_animation_frame():
    source = Path('strategyos_mvp/static/executive.js').read_text()
    function = source[source.index('  function renderDriverGrid('):source.index('  function renderMetrics(')]
    program = '''
const assert=require('node:assert/strict');
const frames=[];
const window={scrollY:120,scrollTo:()=>{},requestAnimationFrame:fn=>frames.push(fn),setTimeout:fn=>frames.push(fn)};
const buttons=[]; const grid={innerHTML:'',appendChild:x=>buttons.push(x)};
const $=()=>grid;
const state={activeDriverKey:'cost',driverSelectionScrollY:120};
const drivers=[{key:'cost',label:'Cost'},{key:'cash',label:'Cash'}];
const getVisibleDrivers=()=>drivers,getActiveDriver=()=>drivers[0];
const document={createElement:()=>({setAttribute:()=>{},addEventListener:()=>{}})};
const firstDefined=(...xs)=>xs.find(x=>x!==undefined && x!==null && x!=='');
const escapeHtml=x=>x,driverRingMarkup=()=>'',driverCenterMarkup=()=>'',driverSubLabel=()=>'',groundingBadgeMarkup=()=>'';
let composer='cost';
const renderDriverDrillFidelity=()=>{composer=state.activeDriverKey;};
const updateHistory=()=>{},syncDriverSelectionUI=()=>{},renderSummary=()=>{},renderHero=()=>{};
''' + function + '''
renderDriverGrid();
buttons[1].onclick({preventDefault:()=>{}});
assert.equal(state.activeDriverKey,'cash');
assert.equal(composer,'cash');
assert(frames.length>0,'Scroll correction remains deferred');
'''
    subprocess.run(['node', '-e', program], check=True, capture_output=True, text=True)
