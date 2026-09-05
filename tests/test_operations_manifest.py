import json
from dataclasses import replace

from strategyos_mvp import operations_api, run_registry


def test_deployment_never_attaches_stale_image_to_new_revision(monkeypatch, tmp_path):
    monkeypatch.setattr(operations_api, 'CONFIG', replace(operations_api.CONFIG, workspace_root=tmp_path))
    monkeypatch.setattr(run_registry, 'load_latest_run_summary', lambda: {})
    monkeypatch.setenv('STRATEGYOS_RELEASE_SHA', 'new-release')
    path = tmp_path / '.strategyos_mvp_data/releases/current.json'
    path.parent.mkdir(parents=True)
    manifest = {'application_revision': 'old-release', 'image_digest': 'old-image', 'schema_sha256': 'old-schema'}
    path.write_text(json.dumps(manifest))
    result = operations_api.deployment(principal={'role': 'executive'})
    assert result['application_revision'] == 'new-release'
    assert result['image_digest'] is None and result['schema_sha256'] is None
    assert result['manifest_application_matches'] is False
    manifest.update(application_revision='new-release', image_digest='new-image', schema_sha256='new-schema')
    path.write_text(json.dumps(manifest))
    result = operations_api.deployment(principal={'role': 'executive'})
    assert result['image_digest'] == 'new-image' and result['schema_sha256'] == 'new-schema'
    assert result['manifest_application_matches'] is True
