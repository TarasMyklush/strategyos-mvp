from pathlib import Path
import json
import subprocess
import pytest

STATIC = Path(__file__).parents[1] / 'strategyos_mvp/static'


@pytest.mark.parametrize('page',['index','executive','claims','source-intake','claim-intake','claim-recalculation'])
def test_private_workspaces_share_session_boundary(page):
    assert (STATIC / (page+'.html')).read_text().count('src="/static/session-boundary.js"') == 1


@pytest.mark.parametrize('event,kind,expected', [
    ({'key':'strategyos.ui.token','oldValue':'old','newValue':'new'},'storage','reload'),
    ({'key':'strategyos.ui.token','oldValue':'old','newValue':None},'storage','/login'),
    ({'key':'colour-theme','oldValue':'light','newValue':'dark'},'storage',None),
    ({'key':'strategyos.ui.session-change','oldValue':None,'newValue':'{"signedOut":false,"nonce":"new"}'},'storage','reload'),
    ({'key':'strategyos.ui.session-change','oldValue':None,'newValue':'{"signedOut":true,"nonce":"new"}'},'storage','/login'),
    ({'persisted':True},'pageshow','reload'),
    ({'persisted':False},'pageshow',None),
])
def test_changed_session_cannot_keep_rendered_private_evidence(event,kind,expected):
    source=(STATIC/'session-boundary.js').read_text()
    program='''const assert=require('node:assert/strict');
const handlers={}; const calls=[];
global.window={setInterval:()=>{},addEventListener:(key,fn)=>handlers[key]=fn,location:{replace:x=>calls.push(x),reload:()=>calls.push('reload')}};
global.document={addEventListener:()=>{},createElement:()=>({setAttribute:()=>{}}),documentElement:{replaceChildren:()=>calls.push('clear')}};
''' + source + '\nhandlers['+json.dumps(kind)+']('+json.dumps(event)+');\n' + (
        "assert.deepEqual(calls,['clear',"+json.dumps(expected)+']);' if expected else 'assert.deepEqual(calls,[]);')
    subprocess.run(['node','-e',program],check=True,capture_output=True,text=True)


@pytest.mark.parametrize('trigger',['timer','focus','visibilitychange'])
@pytest.mark.parametrize('new_cookie,expected',[
    ('strategyos_session_epoch=new','reload'), ('','/login'),
    ('strategyos_session_epoch=old; theme=dark',None),
])
def test_cookie_only_session_changes_clear_without_storage_event(trigger,new_cookie,expected):
    source=(STATIC/'session-boundary.js').read_text()
    program='''const assert=require('node:assert/strict');
const handlers={}; const calls=[];
global.window={setInterval:fn=>handlers.timer=fn,addEventListener:(key,fn)=>handlers[key]=fn,location:{replace:x=>calls.push(x),reload:()=>calls.push('reload')}};
global.document={cookie:'strategyos_session_epoch=old',addEventListener:(key,fn)=>handlers[key]=fn,createElement:()=>({setAttribute:()=>{}}),documentElement:{replaceChildren:()=>calls.push('clear')}};
''' + source + '\ndocument.cookie='+json.dumps(new_cookie)+';handlers['+json.dumps(trigger)+']();\n' + (
        "assert.deepEqual(calls,['clear',"+json.dumps(expected)+']);' if expected else 'assert.deepEqual(calls,[]);')
    subprocess.run(['node','-e',program],check=True,capture_output=True,text=True)
