import json
import pytest
from strategyos_mvp import api, source_pack
from strategyos_mvp.source_claims import SourceAccessPolicy


def test_upload_contract_preserves_policy_and_uses_authenticated_actor(monkeypatch):
    monkeypatch.setattr(api, "stage_source_pack_uploads", lambda files, source_contract: source_contract)
    policy = {"allowed_roles": ["executive"], "allowed_purposes": ["executive_briefing"],
              "external_model_allowed": False}
    result = api.create_source_pack(files=[], source_contract_json=json.dumps({
        "source_key": "offline-research", "access_policy": policy,
        "confirmed_by": "forged", "capture_method": "api",
    }), principal={"subject": "operator:real"})
    assert result["access_policy"] == policy
    assert result["confirmed_by"] == "operator:real"
    assert result["capture_method"] == "file_upload"


def test_folder_intake_retains_explicit_source_rights(monkeypatch):
    monkeypatch.setattr(api, "stage_source_pack_from_path", lambda path, source_contract: source_contract)
    result = api.create_source_pack_from_path(api.SourcePackPathRequest(
        folder_path="/fixture", source_key="research", origin_category="public_web",
        allowed_roles=["executive"], allowed_purposes=["executive_briefing"],
    ), principal={"subject": "operator:real"})
    assert result["capture_method"] == "folder_import"
    assert result["access_policy"]["allowed_roles"] == ["executive"]
    assert result["access_policy"]["external_model_allowed"] is False


@pytest.mark.parametrize("value", ["false", "true", 1, 0, None])
def test_consent_is_never_inferred_from_truthiness(value):
    with pytest.raises(ValueError, match="explicit boolean"):
        SourceAccessPolicy(source_key="test", allowed_roles=frozenset({"executive"}),
            allowed_purposes=frozenset({"executive_briefing"}), external_model_allowed=value)
    with pytest.raises(api.HTTPException) as error:
        source_pack.normalize_source_contract(source_pack_id="fixture", source_kind="browser_upload",
            contract={"access_policy": {"allowed_roles": ["executive"],
                "allowed_purposes": ["executive_briefing"], "external_model_allowed": value}})
    assert error.value.status_code == 422
