import hashlib
import json
from dataclasses import replace

import pytest

from strategyos_mvp import staged_evidence, source_pack, claim_api
from strategyos_mvp.source_claims import PolicyContext, UsePurpose


@pytest.fixture
def staged(tmp_path, monkeypatch):
    root = tmp_path / 'pack'
    (root / 'raw').mkdir(parents=True)
    content = b'Synthetic evidence only'
    (root / 'raw/note.txt').write_bytes(content)
    payload = {'tenant_context':{'tenant_id':'tenant-one'}, 'source_kind':'browser_upload',
        'source_contract':{'source_key':'source-one','display_name':'Synthetic source',
            'origin_category':'internal_system','confirmed_by':'steward','governed_owner':'data-owner',
            'authorization_basis':'Synthetic fixture authority',
            'access_policy':{'storage_allowed':True,'allowed_roles':['operator'],'allowed_purposes':['operations']}},
        'manifest':[{'relative_path':'note.txt','sha256':hashlib.sha256(content).hexdigest()}]}
    (root / 'summary.json').write_text(json.dumps(payload))
    monkeypatch.setattr(source_pack, '_source_pack_dir', lambda pack: root)
    context = PolicyContext(tenant_id='tenant-one',principal_id='operator-one',
                            roles=frozenset({'operator'}),purpose=UsePurpose.OPERATIONS)
    return root, payload, context


class Repository:
    def __init__(self):
        self.calls = []
    def register_source(self, source, **kwargs):
        self.calls.append(('source',source,kwargs))
        assert kwargs['create_only'] is True
        return {'registration_version':1}
    def record_occurrence(self, occurrence, **kwargs):
        self.calls.append(('occurrence',occurrence,kwargs))
        return {'occurrence_key':occurrence.occurrence_key,'evidence_occurrence_id':'receipt'}


def test_staged_handoff_records_only_hash_verified_evidence(staged):
    root, payload, context = staged
    repo = Repository()
    result = staged_evidence.register_staged_evidence('pack','note.txt',context=context,repository=repo)
    assert result['claims_created'] == 0 and not result['analysis_started'] and not result['outbound_delivery']
    assert len(repo.calls) == 2
    assert repo.calls[0][2]['recorded_by'] == context.principal_id
    policy = repo.calls[0][2]['policy']
    assert not policy.external_model_allowed and not policy.index_allowed
    assert repo.calls[1][2]['artifact']['size_bytes'] == len((root/'raw/note.txt').read_bytes())


@pytest.mark.parametrize('case',['foreign_tenant','changed_hash','unknown_origin','no_storage','path_traversal','symlink'])
def test_invalid_handoff_never_reaches_repository(staged, case):
    root, payload, context = staged
    selected = 'note.txt'
    if case == 'foreign_tenant': context = replace(context,tenant_id='tenant-two')
    if case == 'changed_hash': (root/'raw/note.txt').write_bytes(b'Changed bytes')
    if case == 'unknown_origin': payload['source_contract']['origin_category'] = 'unknown'
    if case == 'no_storage': payload['source_contract']['access_policy']['storage_allowed'] = False
    if case == 'path_traversal':
        selected = '../summary.json'
        payload['manifest'][0]['relative_path'] = selected
    if case == 'symlink':
        (root/'raw/note.txt').unlink()
        (root/'raw/note.txt').symlink_to(root/'summary.json')
    (root/'summary.json').write_text(json.dumps(payload))
    repo = Repository()
    with pytest.raises((ValueError,PermissionError)):
        staged_evidence.register_staged_evidence('pack',selected,context=context,repository=repo)
    assert not repo.calls


def test_staged_registration_route_rejects_executive_role():
    from fastapi import HTTPException
    route = next(r for r in claim_api.router.routes if r.path == '/api/claims/intake/staged-evidence')
    with pytest.raises(HTTPException) as denied:
        route.dependant.dependencies[0].call(principal={'role':'executive'})
    assert denied.value.status_code == 403


def test_unreadable_staged_bytes_do_not_expose_server_paths(staged, monkeypatch):
    from pathlib import Path
    root, _, context = staged
    original = Path.open
    def unavailable(path, *args, **kwargs):
        if path == root / 'raw/note.txt':
            raise PermissionError('/private/server/path')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', unavailable)
    repo = Repository()
    with pytest.raises(ValueError, match='Stage it again') as error:
        staged_evidence.register_staged_evidence('pack', 'note.txt', context=context, repository=repo)
    assert '/private' not in str(error.value)
    assert not repo.calls
