import pytest

from strategyos_mvp import state_store
from strategyos_mvp.state_store import migration_path, schema_path


def test_schema_has_immutable_migration_ledger():
    schema = schema_path().read_text(encoding="utf-8")
    assert "create table if not exists strategyos_schema_migrations" in schema


def test_common_source_claim_migration_defines_required_layers():
    migration = (migration_path() / "0001_common_source_claim.sql").read_text(encoding="utf-8")
    for table in (
        "strategyos_source_access_policies",
        "strategyos_source_registration_versions",
        "strategyos_evidence_occurrences",
        "strategyos_claim_families",
        "strategyos_claim_revisions",
        "strategyos_claim_evidence_links",
        "strategyos_claim_assessments",
        "strategyos_claim_dependencies",
        "strategyos_analysis_snapshots",
        "strategyos_analysis_snapshot_claims",
        "strategyos_claim_projection_outbox",
    ):
        assert f"create table if not exists {table}" in migration


def test_migration_separates_origin_kind_assessment_and_permissions():
    migration = (migration_path() / "0001_common_source_claim.sql").read_text(encoding="utf-8")
    assert "origin_category" in migration
    assert "claim_kind" in migration
    assert "strategyos_claim_assessments" in migration
    assert "allowed_roles" in migration
    assert "external_model_allowed" in migration
    assert "supersedes_revision_id" in migration
    assert "payload_fingerprint" in migration
    assert "unique (tenant_id, occurrence_key)" in migration


def test_claim_schema_keeps_financial_values_decimal_and_requires_numeric_units():
    migration = (migration_path() / "0001_common_source_claim.sql").read_text(encoding="utf-8")
    assert "value_numeric numeric" in migration
    assert "value_numeric is null or nullif(btrim(unit), '') is not null" in migration
    assert "claim_kind <> 'forecast' or nullif(btrim(author_identity), '') is not null" in migration


class MigrationCursor:
    def __init__(self):
        self.applied = {}
        self._row = None
        self.executed = []

    def execute(self, statement, params=None):
        normalized = " ".join(statement.split())
        self.executed.append((normalized, params))
        if normalized.startswith("select checksum_sha256"):
            checksum = self.applied.get(params[0])
            self._row = (checksum,) if checksum else None
        elif normalized.startswith("insert into strategyos_schema_migrations"):
            self.applied[params[0]] = params[1]
            self._row = None
        else:
            self._row = None

    def fetchone(self):
        return self._row


def test_migration_runner_is_idempotent_and_detects_changed_history(tmp_path, monkeypatch):
    root = tmp_path / "migrations"
    root.mkdir()
    migration = root / "0001_example.sql"
    migration.write_text("create table example (id integer);", encoding="utf-8")
    monkeypatch.setattr(state_store, "migration_path", lambda: root)
    cursor = MigrationCursor()
    assert state_store.apply_schema_migrations(cursor) == ["0001"]
    assert state_store.apply_schema_migrations(cursor) == []
    migration.write_text("create table example (id bigint);", encoding="utf-8")
    with pytest.raises(RuntimeError, match="no longer matches"):
        state_store.apply_schema_migrations(cursor)
