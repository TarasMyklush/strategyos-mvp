from fastapi import FastAPI
from fastapi.testclient import TestClient

from strategyos_mvp import claim_api
from tests.test_tabular_claims import mapping, workbook


def client_for(role, monkeypatch):
    app = FastAPI()
    app.include_router(claim_api.router)
    route = next(r for r in claim_api.router.routes if r.path == "/api/claims/intake/workbook")
    # Exercise multipart validation with the authenticated role dependency fixed;
    # role enforcement itself is separately checked against the application.
    app.dependency_overrides[route.dependant.dependencies[0].call] = lambda: {
        "role": role, "subject": "operator", "tenant_id": "tenant"}
    return TestClient(app)


def test_multipart_preview_binds_hash_tenant_and_explicit_contract(monkeypatch):
    import hashlib
    captured = {}
    class Repo:
        def ingest_mapped_table(self, rows, contract, **kwargs):
            captured.update(rows=rows, contract=contract, **kwargs)
            return {"status":"preview", "claim_count":1}
    monkeypatch.setattr(claim_api, "ClaimRepository", Repo)
    content = workbook([["BU", "From", "To", "Value", "Kind", "Author"],
                       ["retail", "2026-06-01", "2026-06-30", 0, "actual", None]])
    client = client_for("operator", monkeypatch)
    response = client.post("/api/claims/intake/workbook", data={
        "mapping_json":mapping().model_dump_json(), "occurrence_key":"evidence"},
        files={"file":("finance.xlsx", content)})
    assert response.status_code == 200, response.text
    assert captured["apply"] is False
    assert captured["source_hash"] == hashlib.sha256(content).hexdigest()
    assert captured["context"].tenant_id == "tenant"
    assert captured["rows"][0]["Value"] == 0


def test_wrong_format_never_reaches_ledger(monkeypatch):
    response = client_for("operator", monkeypatch).post("/api/claims/intake/workbook",
        data={"mapping_json":mapping().model_dump_json(), "occurrence_key":"evidence"},
        files={"file":("file.csv", b"a,b")})
    assert response.status_code == 422


def test_operator_workspace_uses_preview_and_safe_text_only():
    from pathlib import Path
    static = Path(__file__).resolve().parents[1] / "strategyos_mvp/static"
    script = (static / "claim-intake.js").read_text()
    assert "innerHTML" not in script
    assert "record ? 'true' : 'false'" in script
    assert "ticket !== generation" in script
    html = (static / "claim-intake.html").read_text()
    assert 'id="intake-apply" type="button" disabled' in html
