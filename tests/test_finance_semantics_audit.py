import hashlib
from unittest.mock import MagicMock

import pytest
from strategyos_mvp import finance_semantics_audit as audit


def fixture_audit(monkeypatch, tmp_path, *, digest=None, paths=None):
    artifact = tmp_path / "finance.xlsx"
    artifact.write_bytes(b"synthetic fixture bytes")
    connection = MagicMock()
    cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (str(tmp_path),'tenant-fixture')
    monkeypatch.setattr(audit, "database_connection", lambda: (connection, None))
    monkeypatch.setattr(audit, "derive_source_finance_kpis", lambda _: {
        "source_files": ["finance.xlsx"], "source_semantics_version": "2",
        "ambiguous_components": {"revenue_actual": {"value": "100", "reason": "Actual/Est"}}})
    responses = iter([
        [{"source_path": path, "source_hash": digest or hashlib.sha256(artifact.read_bytes()).hexdigest()}
         for path in (paths or ["finance.xlsx"])],
        [{"id": "revision", "claim_kind": "actual", "metric_key": "ceo.revenue",
          "dimensions": {"component_key": "revenue_actual"}}],
    ])
    monkeypatch.setattr(audit, "fetchall_dicts", lambda _: next(responses))
    return cursor


def test_audit_verifies_bytes_and_never_writes(monkeypatch, tmp_path):
    cursor = fixture_audit(monkeypatch, tmp_path)
    result = audit.audit_run("run")
    assert result["approved_snapshot_modified"] is False
    assert result["review_required"][0]["claim_revision_id"] == "revision"
    assert all(call.args[0].lstrip().lower().startswith("select") for call in cursor.execute.call_args_list)


def test_changed_source_cannot_be_used_to_adjudicate_old_claim(monkeypatch, tmp_path):
    fixture_audit(monkeypatch, tmp_path, digest="0"*64)
    with pytest.raises(ValueError, match="Source bytes do not match"):
        audit.audit_run("run")


def test_normalized_alias_requires_exact_bytes_and_reports_original_path(monkeypatch, tmp_path):
    fixture_audit(monkeypatch, tmp_path, paths=["historic/finance.xlsx"])
    result = audit.audit_run("run")
    assert result["checked_sources"][0]["recorded_source_path"] == "historic/finance.xlsx"
    assert result["checked_sources"][0]["source_path"] == "finance.xlsx"


def test_multiple_identical_occurrences_cannot_be_silently_merged(monkeypatch, tmp_path):
    fixture_audit(monkeypatch, tmp_path, paths=["first/finance.xlsx", "second/finance.xlsx"])
    with pytest.raises(ValueError, match="Source bytes do not match"):
        audit.audit_run("run")


def test_negative_validation_requires_matching_reviewed_audit(monkeypatch, tmp_path):
    fixture_audit(monkeypatch,tmp_path)
    from strategyos_mvp import claim_store
    monkeypatch.setattr(claim_store,'ClaimRepository',lambda:pytest.fail('Wrote without matching digest'))
    with pytest.raises(ValueError,match='Audit changed'):
        audit.record_invalidity('run',expected_audit_digest='wrong')
