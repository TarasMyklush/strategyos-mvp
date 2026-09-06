"""An aggregate board score must not erase the selected business exception."""
import json
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize('tone,score,expected',[
    ('down',101,'Intervention needed'),
    ('watch',101,'Needs review'),
    ('up',101,'Board aggregate: On plan'),
    ('flat',None,'Current'),
])
def test_exception_overrides_aggregate_status(tone,score,expected):
    source=(Path(__file__).parents[1]/'strategyos_mvp/static/executive.js').read_text()
    block=source.split('    var reviewGate = !hasScore',1)[1].split('    var heroStatusText',1)[0]
    program='const assert=require("node:assert/strict");\n' + (
        'var semanticTone='+json.dumps(tone)+';var hasScore='+json.dumps(score is not None)+';'
        'var hero={},preferredHero={};var firstDefined=(...xs)=>xs.find(x=>x!==undefined);'
        'var planPresentation={verdict:"On plan"};\nvar reviewGate = !hasScore'
    )+block+'\nassert.equal(statusSignal,'+json.dumps(expected)+');'
    subprocess.run(['node','-e',program],check=True,capture_output=True,text=True)
