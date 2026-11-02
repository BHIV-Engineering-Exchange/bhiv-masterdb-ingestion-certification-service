"""
T4 Structured Security Decision Logging Tests.
Validates structured decision logging across fail-closed paths and confirms
sensitive credentials (passwords, tokens, raw authorization headers) are NEVER logged.
"""
import json
import logging
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

import main
from auth.dependencies import get_identity
from auth.service import AuthService, AuthTokenError
from bcaes_registry.service import _has_authority
from operational_sync.service import _check, SyncPermissionDeniedError

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client():
    main.app.dependency_overrides.clear()
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def _extract_security_decisions(caplog) -> list[dict]:
    """Helper to extract structured JSON security decisions from captured log output."""
    decisions = []
    for record in caplog.records:
        msg = record.getMessage()
        if "SECURITY_DECISION:" in msg:
            json_part = msg.split("SECURITY_DECISION:", 1)[1].strip()
            try:
                decisions.append(json.loads(json_part))
            except Exception:
                pass
    return decisions


# ---------------------------------------------------------------------------
# 1. Credentials Redaction: Passwords never logged
# ---------------------------------------------------------------------------
def test_password_never_logged_during_authentication(client, caplog):
    caplog.set_level(logging.DEBUG)
    sensitive_password = "super-secret-user-password-xyz-987"

    resp = client.post(
        "/auth/token",
        json={"actor": "test-user", "password": sensitive_password},
    )

    # Status doesn't matter (401 or 200); what matters is the password is NEVER in log output
    assert sensitive_password not in caplog.text, "Password leaked in log output!"


# ---------------------------------------------------------------------------
# 2. Credentials Redaction: Tokens and Auth headers never logged
# ---------------------------------------------------------------------------
def test_bearer_token_and_auth_header_never_logged(client, caplog):
    caplog.set_level(logging.DEBUG)
    secret_token_string = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.sensitive-token-payload-12345"
    raw_header = f"Bearer {secret_token_string}"

    resp = client.post(
        "/validate",
        json={"dataset_id": "test-ds"},
        headers={"Authorization": raw_header},
    )

    assert secret_token_string not in caplog.text, "Raw JWT token string leaked in log output!"
    assert raw_header not in caplog.text, "Raw Authorization header leaked in log output!"


# ---------------------------------------------------------------------------
# 3. Structured Record Format: All required fields present
# ---------------------------------------------------------------------------
def test_security_decision_log_format_has_all_required_fields(client, caplog):
    caplog.set_level(logging.INFO)
    # Trigger an unauthenticated deny
    resp = client.post("/certify", json={"dataset_id": "test"})
    assert resp.status_code == 401

    decisions = _extract_security_decisions(caplog)
    assert len(decisions) >= 1, "Expected at least one structured security decision log record"

    rec = decisions[-1]
    assert "timestamp" in rec, "Missing timestamp in security decision log"
    assert "correlation_id" in rec, "Missing correlation_id in security decision log"
    assert "request_id" in rec, "Missing request_id in security decision log"
    assert "outcome" in rec, "Missing outcome in security decision log"
    assert rec["outcome"] in ("ALLOW", "DENY")
    assert "reason_code" in rec, "Missing reason_code in security decision log"
    assert "policy_reference" in rec, "Missing policy_reference in security decision log"
    assert "actor_reference" in rec, "Missing actor_reference in security decision log"


# ---------------------------------------------------------------------------
# 4. Correlation ID Tracking
# ---------------------------------------------------------------------------
def test_correlation_id_propagated_to_decision_log(client, caplog):
    caplog.set_level(logging.INFO)
    test_cid = "corr-test-trace-uuid-12345678"

    resp = client.post(
        "/certify",
        json={"dataset_id": "test"},
        headers={"X-Correlation-Id": test_cid},
    )
    assert resp.status_code == 401

    decisions = _extract_security_decisions(caplog)
    matching = [d for d in decisions if d.get("correlation_id") == test_cid]
    assert len(matching) >= 1, f"Expected decision log with correlation_id {test_cid}"
    assert matching[0]["outcome"] == "DENY"
    assert matching[0]["reason_code"] == "DENY:MISSING_IDENTITY"


# ---------------------------------------------------------------------------
# 5. get_identity: ALLOW decision logged for valid token
# ---------------------------------------------------------------------------
def test_get_identity_allow_decision_logged(client, caplog, tmp_path):
    main.artifact_store.reports_dir = tmp_path
    caplog.set_level(logging.INFO)
    token, _ = main.auth_service.issue_token("audited-operator", ["operator"])

    payload = {
        "dataset_id": "api-certifiable",
        "dataset_path": str(ROOT / "datasets" / "certifiable_sample.csv"),
        "metadata_path": str(ROOT / "datasets" / "metadata.json"),
    }
    resp = client.post(
        "/validate",
        json=payload,
        headers={"Authorization": f"Bearer {token}", "X-Request-Id": "req-oper-allow-1"},
    )
    assert resp.status_code == 200

    decisions = _extract_security_decisions(caplog)
    allow_decisions = [d for d in decisions if d.get("outcome") == "ALLOW" and d.get("actor_reference") == "audited-operator"]
    assert len(allow_decisions) >= 1, "Expected ALLOW security decision for audited-operator"
    assert allow_decisions[0]["reason_code"] == "ALLOW:VERIFIED_IDENTITY"
    assert allow_decisions[0]["policy_reference"] == "/validate"


# ---------------------------------------------------------------------------
# 6. bcaes_registry: Fail-closed path logs DENY on actor=None
# ---------------------------------------------------------------------------
def test_bcaes_registry_actor_none_logs_deny(caplog):
    caplog.set_level(logging.INFO)
    outcome = _has_authority(actor=None, actor_roles=["admin"], boundaries=["Kavy"])
    assert outcome is False

    decisions = _extract_security_decisions(caplog)
    deny_decisions = [d for d in decisions if d.get("policy_reference") == "bcaes_registry._has_authority" and d.get("outcome") == "DENY"]
    assert len(deny_decisions) >= 1
    assert deny_decisions[0]["reason_code"] == "DENY:MISSING_IDENTITY"
    assert deny_decisions[0]["actor_reference"] == "None"


# ---------------------------------------------------------------------------
# 7. operational_sync: Fail-closed path logs DENY on actor=None
# ---------------------------------------------------------------------------
def test_operational_sync_actor_none_logs_deny(caplog):
    caplog.set_level(logging.INFO)
    with pytest.raises(PermissionError):
        _check(actor=None, actor_roles=["admin"], required_role="parikshak-sync")

    decisions = _extract_security_decisions(caplog)
    deny_decisions = [d for d in decisions if d.get("policy_reference") == "operational_sync._check" and d.get("outcome") == "DENY"]
    assert len(deny_decisions) >= 1
    assert deny_decisions[0]["reason_code"] == "DENY:MISSING_IDENTITY"
    assert deny_decisions[0]["actor_reference"] == "None"


# ---------------------------------------------------------------------------
# 8. auth/service: Fail-closed escalation path logs DENY:MISSING_ADMIN_PASSWORD
# ---------------------------------------------------------------------------
def test_auth_service_missing_admin_password_logs_deny(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setenv("AUTH_PASSWORD", "standard-secret")
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    svc = AuthService()
    with pytest.raises(AuthTokenError):
        svc.authenticate(actor="kavy", password="standard-secret")

    decisions = _extract_security_decisions(caplog)
    deny_decisions = [d for d in decisions if d.get("reason_code") == "DENY:MISSING_ADMIN_PASSWORD"]
    assert len(deny_decisions) >= 1
    assert deny_decisions[0]["outcome"] == "DENY"
    assert deny_decisions[0]["actor_reference"] == "kavy"
    assert "standard-secret" not in caplog.text, "Password leaked in log output!"

