"""Pure-unit tests for agent_runtime.capability_tokens -- no Postgres
required. Covers design doc section 13: issue/verify round trip, tamper
detection, expiry, tool-key scoping, and risk-class ceiling enforcement.
"""

from __future__ import annotations

import os
import time

import pytest

from strategyos_mvp.agent_runtime import capability_tokens as ct
from strategyos_mvp.config import load_config


def _apply_env(env_updates: dict[str, str | None]):
    original = {key: os.environ.get(key) for key in env_updates}
    for key, value in env_updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    ct.CONFIG = load_config()
    return original


def _restore_env(original: dict[str, str | None]):
    for key, value in original.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    ct.CONFIG = load_config()


@pytest.fixture
def with_secret():
    original = _apply_env({"STRATEGYOS_AGENT_CAPABILITY_TOKEN_SECRET": "unit-test-secret"})
    try:
        yield
    finally:
        _restore_env(original)


def test_issue_and_verify_round_trip(with_secret):
    token = ct.issue_capability_token(
        tenant_id="t1", task_id="task1", attempt_no=1, agent_installation_id="inst1",
        allowed_tool_keys=("findings.read",), max_risk_class="read_only",
    )
    claims = ct.verify_capability_token(token)
    assert claims.tenant_id == "t1"
    assert claims.task_id == "task1"
    assert claims.allowed_tool_keys == ("findings.read",)
    assert claims.max_risk_class == "read_only"


def test_verify_fails_without_secret_configured():
    original = _apply_env({"STRATEGYOS_AGENT_CAPABILITY_TOKEN_SECRET": None})
    try:
        with pytest.raises(ct.CapabilityTokenSecretMissing):
            ct.issue_capability_token(
                tenant_id="t1", task_id="task1", attempt_no=1, agent_installation_id="inst1",
                allowed_tool_keys=("findings.read",),
            )
    finally:
        _restore_env(original)


def test_tampered_payload_is_rejected(with_secret):
    token = ct.issue_capability_token(
        tenant_id="t1", task_id="task1", attempt_no=1, agent_installation_id="inst1",
        allowed_tool_keys=("findings.read",),
    )
    payload_b64, signature_b64 = token.split(".", 1)
    tampered = payload_b64 + "X" + "." + signature_b64
    with pytest.raises(ct.CapabilityTokenInvalid):
        ct.verify_capability_token(tampered)


def test_tampered_signature_is_rejected(with_secret):
    token = ct.issue_capability_token(
        tenant_id="t1", task_id="task1", attempt_no=1, agent_installation_id="inst1",
        allowed_tool_keys=("findings.read",),
    )
    payload_b64, signature_b64 = token.split(".", 1)
    tampered = payload_b64 + "." + signature_b64[:-4] + "AAAA"
    with pytest.raises(ct.CapabilityTokenInvalid):
        ct.verify_capability_token(tampered)


def test_malformed_token_is_rejected(with_secret):
    with pytest.raises(ct.CapabilityTokenInvalid):
        ct.verify_capability_token("not-a-valid-token-at-all")


def test_a_token_signed_with_a_different_secret_is_rejected(with_secret):
    token = ct.issue_capability_token(
        tenant_id="t1", task_id="task1", attempt_no=1, agent_installation_id="inst1",
        allowed_tool_keys=("findings.read",),
    )
    original = _apply_env({"STRATEGYOS_AGENT_CAPABILITY_TOKEN_SECRET": "a-different-secret"})
    try:
        with pytest.raises(ct.CapabilityTokenInvalid):
            ct.verify_capability_token(token)
    finally:
        _restore_env(original)


def test_expired_token_is_rejected_after_real_wait(with_secret):
    token = ct.issue_capability_token(
        tenant_id="t1", task_id="task1", attempt_no=1, agent_installation_id="inst1",
        allowed_tool_keys=("findings.read",), ttl_seconds=1,
    )
    time.sleep(1.2)
    with pytest.raises(ct.CapabilityTokenExpired):
        ct.verify_capability_token(token)


def test_authorize_tool_call_allows_a_tool_in_scope(with_secret):
    token = ct.issue_capability_token(
        tenant_id="t1", task_id="task1", attempt_no=1, agent_installation_id="inst1",
        allowed_tool_keys=("findings.read", "citations.search"), max_risk_class="read_only",
    )
    claims = ct.verify_capability_token(token)
    ct.authorize_tool_call(claims, tool_key="findings.read", tool_risk_class="read_only")  # must not raise


def test_authorize_tool_call_rejects_a_tool_outside_the_allowlist(with_secret):
    token = ct.issue_capability_token(
        tenant_id="t1", task_id="task1", attempt_no=1, agent_installation_id="inst1",
        allowed_tool_keys=("findings.read",), max_risk_class="restricted",
    )
    claims = ct.verify_capability_token(token)
    with pytest.raises(ct.CapabilityTokenInvalid):
        ct.authorize_tool_call(claims, tool_key="publication.release", tool_risk_class="restricted")


def test_authorize_tool_call_rejects_risk_class_escalation_even_when_tool_key_matches(with_secret):
    """Defense in depth: allowed_tool_keys containing a key is not
    sufficient on its own -- the token's max_risk_class ceiling must also
    cover the tool's actual risk class."""
    token = ct.issue_capability_token(
        tenant_id="t1", task_id="task1", attempt_no=1, agent_installation_id="inst1",
        allowed_tool_keys=("publication.release",), max_risk_class="read_only",
    )
    claims = ct.verify_capability_token(token)
    with pytest.raises(ct.CapabilityTokenInvalid):
        ct.authorize_tool_call(claims, tool_key="publication.release", tool_risk_class="restricted")


def test_authorize_tool_call_allows_a_call_at_exactly_the_risk_ceiling(with_secret):
    token = ct.issue_capability_token(
        tenant_id="t1", task_id="task1", attempt_no=1, agent_installation_id="inst1",
        allowed_tool_keys=("publication.release",), max_risk_class="restricted",
    )
    claims = ct.verify_capability_token(token)
    ct.authorize_tool_call(claims, tool_key="publication.release", tool_risk_class="restricted")  # must not raise


def test_authorize_tool_call_allows_a_lower_risk_call_under_a_higher_ceiling(with_secret):
    token = ct.issue_capability_token(
        tenant_id="t1", task_id="task1", attempt_no=1, agent_installation_id="inst1",
        allowed_tool_keys=("findings.read",), max_risk_class="restricted",
    )
    claims = ct.verify_capability_token(token)
    ct.authorize_tool_call(claims, tool_key="findings.read", tool_risk_class="read_only")  # must not raise


def test_each_issued_token_has_a_unique_nonce(with_secret):
    token1 = ct.issue_capability_token(
        tenant_id="t1", task_id="task1", attempt_no=1, agent_installation_id="inst1",
        allowed_tool_keys=("findings.read",),
    )
    token2 = ct.issue_capability_token(
        tenant_id="t1", task_id="task1", attempt_no=1, agent_installation_id="inst1",
        allowed_tool_keys=("findings.read",),
    )
    claims1 = ct.verify_capability_token(token1)
    claims2 = ct.verify_capability_token(token2)
    assert claims1.nonce != claims2.nonce
