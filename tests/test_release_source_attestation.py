import hashlib
import importlib.util
import json
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('release_attestation',Path(__file__).resolve().parents[1]/'deploy/scripts/record_release.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_ingestion_manifest_is_checkpoint_bound_and_verifies_source_bytes(tmp_path):
    source=tmp_path/'source';source.mkdir()
    run=tmp_path/'run';run.mkdir()
    artifact=source/'facts.csv';artifact.write_text('value\n100\n')
    sealed=run/'source_hash_manifest.json'
    sealed.write_text(json.dumps({'facts.csv':{'path':'facts.csv','sha256':module.sha(artifact)}}))
    (run/'StrategyOS Governed Release Receipt.json').write_text(json.dumps({
        'approved_checkpoint_fingerprint':'checkpoint',
        'source_artifacts':{'manifest':{'sha256':module.sha(sealed)}}}))
    result=module.verify_source_manifest(source,run)
    assert len(result['files'])==1 and result['classification']=='not_declared'
    artifact.write_text('value\n999\n')
    with pytest.raises(ValueError,match='changed'):module.verify_source_manifest(source,run)
    # Editing both source and loose manifest cannot rewrite the checkpoint seal.
    sealed.write_text(json.dumps({'facts.csv':{'path':'facts.csv','sha256':module.sha(artifact)}}))
    with pytest.raises(ValueError,match='checkpoint'):module.verify_source_manifest(source,run)


def test_release_manifest_cannot_escape_its_source_root(tmp_path):
    source=tmp_path/'source';source.mkdir()
    outside=tmp_path/'private';outside.write_text('private')
    (source/'release-source-manifest.json').write_text(json.dumps({'files':[{
        'pack_path':'../private','sha256':module.sha(outside)}]}))
    with pytest.raises(ValueError,match='outside'):module.verify_source_manifest(source,tmp_path)



def test_branch_deployment_attests_after_governed_surface_check():
    text=(Path(__file__).resolve().parents[1]/'.github/workflows/strategyos-branch-deploy.yml').read_text()
    assert text.index('name: Verify governed cloud surface') < text.index('name: Attest deployed revision and approved source snapshot')
    assert 'python3 deploy/scripts/record_release.py --base' in text
