from types import SimpleNamespace

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


def test_backfill_migration_persists_reconciliation_and_exceptions():
    migration = (migration_path() / "0002_claim_backfill_reconciliation.sql").read_text(
        encoding="utf-8"
    )
    assert "create table if not exists strategyos_claim_backfill_exceptions" in migration
    assert "create table if not exists strategyos_claim_reconciliations" in migration
    assert "source_record_count" in migration
    assert "claim_record_count" in migration
    assert "difference_sar" in migration


def test_projection_delivery_migration_adds_leases_and_cache_projection():
    migration = (migration_path() / "0003_claim_projection_delivery.sql").read_text(
        encoding="utf-8"
    ).lower()
    assert "available_at timestamptz" in migration
    assert "locked_by text" in migration
    assert "dead_lettered_at timestamptz" in migration
    assert "create table if not exists strategyos_claim_projection_cache" in migration


def test_claim_projector_is_an_explicit_rollout_profile():
    compose = (schema_path().parents[1] / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    projector = compose.split("  strategyos-claim-projector:", 1)[1].split(
        "\n  strategyos-idp:", 1
    )[0]
    assert 'profiles: ["governed-claims"]' in projector
    assert "STRATEGYOS_EMBEDDING_MODEL_PATH" in projector


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


def test_schema_initialization_is_cached_per_real_database(tmp_path, monkeypatch):
    schema = tmp_path / "schema.sql"
    schema.write_text("create table example (id integer);", encoding="utf-8")
    monkeypatch.setattr(state_store, "schema_path", lambda: schema)
    migration_calls = []
    monkeypatch.setattr(
        state_store,
        "apply_schema_migrations",
        lambda cursor: migration_calls.append(cursor) or [],
    )

    class Cursor:
        def __init__(self, statements):
            self.statements = statements

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement, _params=None):
            self.statements.append(" ".join(statement.split()))

    class Connection:
        def __init__(self):
            self.info = SimpleNamespace(
                host="postgres", port=5432, dbname="schema-cache-test", user="strategyos"
            )
            self.statements = []
            self.commits = 0

        def cursor(self):
            return Cursor(self.statements)

        def commit(self):
            self.commits += 1

    key = ("postgres", "5432", "schema-cache-test", "strategyos")
    state_store._SCHEMA_READY_DATABASES.discard(key)
    first = Connection()
    second = Connection()
    try:
        state_store.ensure_data_schema(first)
        state_store.ensure_data_schema(second)
    finally:
        state_store._SCHEMA_READY_DATABASES.discard(key)

    assert first.statements == ["create table example (id integer)"]
    assert first.commits == 1
    assert len(migration_calls) == 1
    assert second.statements == []
    assert second.commits == 0
