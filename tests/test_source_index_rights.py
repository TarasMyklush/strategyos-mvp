from types import SimpleNamespace

import pytest
from strategyos_mvp import access_scope, neo4j_store, vector_store


@pytest.mark.parametrize("store", ["graph", "vector"])
def test_legacy_index_denial_precedes_content_processing(monkeypatch, tmp_path, store):
    monkeypatch.setattr(access_scope, "source_index_allowed", lambda *args: False)
    artifact = tmp_path / "graph.json"
    artifact.write_text("not valid json: must never be processed")
    if store == "graph":
        monkeypatch.setattr(neo4j_store, "CONFIG", SimpleNamespace(neo4j_uri="bolt://fixture"))
        result = neo4j_store.sync_knowledge_graph(run_id="run", tenant_slug="tenant", knowledge_graph_path=artifact)
    else:
        monkeypatch.setattr(vector_store, "CONFIG", SimpleNamespace(qdrant_url="http://fixture"))
        monkeypatch.setattr(vector_store, "_build_points", lambda **kwargs: pytest.fail("Denied content processed"))
        result = vector_store.sync_findings_vector_store(run_id="run", tenant_slug="tenant", findings=[], knowledge_graph_path=artifact)
    assert result["status"] == "blocked"


def test_background_indexer_uses_system_authority_and_explicit_index_gate(monkeypatch):
    from strategyos_mvp import claim_store
    class Repository:
        def run_source_access(self, run_id, *, context, require_index):
            assert context.roles == frozenset({"system"})
            assert str(context.purpose) == "operations"
            assert require_index is True
            return {"allowed": True}
    monkeypatch.setattr(claim_store, "ClaimRepository", Repository)
    token = access_scope.principal_scope.set(None)
    try:
        assert access_scope.source_index_allowed("run", "tenant")
    finally:
        access_scope.principal_scope.reset(token)


def test_indexer_cannot_cross_request_tenant():
    token = access_scope.principal_scope.set({"tenant_id": "one", "role": "operator"})
    try:
        assert not access_scope.source_index_allowed("run", "two")
    finally:
        access_scope.principal_scope.reset(token)


def test_stale_legacy_vectors_are_not_read_after_revocation(monkeypatch):
    monkeypatch.setattr(access_scope, "guard_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(access_scope, "source_index_allowed", lambda *args: False)
    with pytest.raises(PermissionError, match="Current source permissions"):
        vector_store._run_filter("stale-run")


def test_source_text_index_checks_rights_before_reading_files(monkeypatch):
    from strategyos_mvp import source_search, semantic_embeddings
    monkeypatch.setattr(semantic_embeddings, "configured", lambda: True)
    monkeypatch.setattr(access_scope, "source_index_allowed", lambda *args: False)
    monkeypatch.setattr(source_search, "source_records", lambda *args: pytest.fail("Denied files read"))
    assert source_search.sync_sources(run_id="run", tenant_slug="tenant", evidence=object())["status"] == "blocked"
