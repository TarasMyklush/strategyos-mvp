#!/usr/bin/env python3
"""Attest a running deployment and its approved source pack without changing either.

Run on the Docker host after application health checks. The receipt is replaced
atomically only after every source hash and the application revision agree.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_source_manifest(source, run_dir):
    """Verify either release-pack manifests or the ingestion-sealed run manifest."""
    release = source / 'release-source-manifest.json'
    if release.is_file():
        manifest = json.loads(release.read_text())
    else:
        sealed = run_dir / 'source_hash_manifest.json'
        receipt = json.loads((run_dir / 'StrategyOS Governed Release Receipt.json').read_text())
        expected = ((receipt.get('source_artifacts') or {}).get('manifest') or {}).get('sha256')
        if not expected or sha(sealed) != expected or not receipt.get('approved_checkpoint_fingerprint'):
            raise ValueError('The source manifest is not bound to its governed checkpoint.')
        entries = json.loads(sealed.read_text())
        files = [{'pack_path':item['path'],'sha256':item['sha256']} for item in entries.values()]
        manifest = {'files':files,
            'digest':hashlib.sha256(json.dumps(sorted(files,key=lambda item:item['pack_path']),sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            'classification':'not_declared','period':None,
            'identity_basis':'ingestion-sealed source_hash_manifest.json',
            'sealed_manifest_sha256':expected}
    if not manifest.get('files'):
        raise ValueError('An empty source manifest cannot attest a release.')
    seen=set()
    for entry in manifest['files']:
        relative=entry['pack_path']
        path=(source / relative).resolve()
        if relative in seen or not path.is_relative_to(source.resolve()) or not path.is_file() or sha(path)!=entry['sha256']:
            raise ValueError('A selected source is duplicate, missing, changed or outside its pack.')
        seen.add(relative)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--container', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--approval-basis', required=True)
    args = parser.parse_args()
    meta = json.loads(subprocess.check_output(['docker', 'inspect', args.container]))[0]
    if meta['State'].get('Health', {}).get('Status') != 'healthy':
        raise SystemExit('Application container must be healthy before attestation.')
    revision = meta['Config']['Labels'].get('org.opencontainers.image.revision')
    if not revision or revision == 'unknown':
        raise SystemExit('The application image needs an immutable revision label.')
    mounted = [m for m in meta['Mounts'] if m['Destination'] == '/app/workspace']
    if len(mounted) != 1:
        raise SystemExit('Exactly one governed workspace mount is required.')
    workspace = Path(mounted[0]['Source']).resolve()
    def local(path):
        relative = Path(path).relative_to('/app/workspace')
        result = (workspace / relative).resolve()
        if not result.is_relative_to(workspace):
            raise ValueError('Path escapes the governed workspace.')
        return result
    # Use the application's publication gate, including recovery from an older
    # pointer to a pending run. A raw latest pointer is not a published release.
    selection_code = """
import json
from strategyos_mvp.config import CONFIG
from strategyos_mvp.access_scope import principal_scope
from strategyos_mvp.run_registry import load_latest_run_summary
with_scope = principal_scope.set({'tenant_id':CONFIG.tenant_slug,'subject':'system:release-attestation','role':'system','authenticated':True})
try:
 print(json.dumps(load_latest_run_summary()))
finally:
 principal_scope.reset(with_scope)
"""
    summary = json.loads(subprocess.check_output(
        ['docker','exec',args.container,'python','-c',selection_code]))
    if not summary or summary.get('approval_status') != 'approved' or summary.get('status') != 'completed':
        raise SystemExit('Select an approved, completed run before attestation.')
    source = local(summary['dataset'])
    manifest = verify_source_manifest(source, local(summary['run_dir']))
    app = args.base.resolve() / 'app'
    schema_paths = ['deploy/postgres/schema.sql'] + [
        f'strategyos_mvp/{name}.py' for name in
        ('board_memory', 'decision_lifecycle', 'conversation_state', 'inference_audit')]
    components = {}
    for path in schema_paths:
        # Attest the running image bytes, and ensure the host release matches.
        actual = subprocess.check_output(['docker', 'exec', args.container, 'sha256sum', '/app/' + path]).decode().split()[0]
        if actual != sha(app / path):
            raise SystemExit('Host release and running schema components differ.')
        components[path] = actual
    env = dict(item.split('=', 1) for item in meta['Config']['Env'] if '=' in item)
    receipt = {
        'target': args.target, 'application_revision': revision,
        'image_digest': meta['Image'], 'schema_components': components,
        'schema_sha256': hashlib.sha256(json.dumps(components, sort_keys=True).encode()).hexdigest(),
        'run_id': summary['run_id'], 'source_digest': manifest['digest'],
        'source_file_count': len(manifest['files']), 'source_classification': manifest['classification'],
        'source_period': manifest['period'], 'approval_status': summary['approval_status'],
        'approval_basis': args.approval_basis, 'provider': env.get('STRATEGYOS_LLM_PROVIDER', 'disabled'),
        'source_search': summary.get('source_search'), 'projection_rebuild': summary.get('projection_rebuild'),
        'recorded_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    folder = workspace / '.strategyos_mvp_data/releases'
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / 'current.tmp'
    temporary.write_text(json.dumps(receipt, indent=2))
    os.chown(temporary, workspace.stat().st_uid, workspace.stat().st_gid)
    os.replace(temporary, folder / 'current.json')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
