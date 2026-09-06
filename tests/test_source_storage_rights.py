from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile

from strategyos_mvp import source_pack


@pytest.mark.parametrize("grant", [None, {}, {"storage_allowed": False}, {"storage_allowed": "true"}])
@pytest.mark.parametrize("method", ["folder", "upload"])
def test_storage_denied_before_source_content_is_read_or_written(monkeypatch, grant, method):
    def unexpected(*args, **kwargs):
        pytest.fail("Source content must not be accessed without explicit storage rights")

    monkeypatch.setattr(source_pack, "_source_pack_id_for_tree", unexpected)
    monkeypatch.setattr(source_pack, "_source_pack_id_for_uploads", unexpected)
    monkeypatch.setattr(source_pack, "_raw_dir", unexpected)
    contract = {"access_policy": grant} if grant is not None else None
    with pytest.raises(HTTPException) as error:
        if method == "folder":
            source_pack.stage_source_pack_from_path("/does-not-exist", source_contract=contract)
        else:
            source_pack.stage_source_pack_uploads(
                [UploadFile(filename="sample.csv", file=BytesIO(b"value\n1\n"))],
                source_contract=contract,
            )
    assert error.value.status_code in {403, 422}


def test_storage_consent_does_not_grant_other_rights():
    result = source_pack.normalize_source_contract(
        source_pack_id="fixture", source_kind="browser_upload",
        contract={"access_policy": {"storage_allowed": True}},
    )
    assert result["access_policy"]["storage_allowed"] is True
    for field in ("index_allowed", "export_allowed", "external_model_allowed", "quote_allowed"):
        assert result["access_policy"][field] is False
