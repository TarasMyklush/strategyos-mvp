from strategyos_mvp.config import load_config
from strategyos_mvp.sensitive_ids import tokenize_sensitive_identifier


def test_sensitive_identifier_tokens_are_tenant_scoped_and_rotation_friendly(monkeypatch):
    monkeypatch.setenv("STRATEGYOS_SENSITIVE_IDENTIFIER_HMAC_KEYS", "v1=alpha-secret,v2=beta-secret")
    monkeypatch.setenv("STRATEGYOS_SENSITIVE_IDENTIFIER_ACTIVE_KEY_ID", "v1")
    monkeypatch.setenv("STRATEGYOS_TENANT_SLUG", "tenant-a")
    config_v1 = load_config()

    token_v1 = tokenize_sensitive_identifier("300187452100003", field_name="Tax_ID", config=config_v1)

    monkeypatch.setenv("STRATEGYOS_SENSITIVE_IDENTIFIER_ACTIVE_KEY_ID", "v2")
    config_v2 = load_config()
    token_v2 = tokenize_sensitive_identifier("300187452100003", field_name="Tax_ID", config=config_v2)

    monkeypatch.setenv("STRATEGYOS_SENSITIVE_IDENTIFIER_ACTIVE_KEY_ID", "v1")
    monkeypatch.setenv("STRATEGYOS_TENANT_SLUG", "tenant-b")
    config_other_tenant = load_config()
    token_other_tenant = tokenize_sensitive_identifier("300187452100003", field_name="Tax_ID", config=config_other_tenant)

    assert token_v1.startswith("hmac:v1:")
    assert token_v2.startswith("hmac:v2:")
    assert token_v1 != token_v2
    assert token_v1 != token_other_tenant
