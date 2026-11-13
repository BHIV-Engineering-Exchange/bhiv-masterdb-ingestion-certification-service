"""
T2 Authorization and Access Control Test Suite.
Validates the explicit fail-closed authorization hardening implemented in T2.
"""
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

import main
from auth.models import AuthIdentity
from auth.service import AuthService, AuthTokenError
from bcaes_registry.service import _has_authority
from operational_sync.service import _check

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client():
    # Clear any leftover dependency overrides
    main.app.dependency_overrides.clear()
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def _make_auth_header(actor: str = "test-operator", roles: list = None) -> dict:
    if roles is None:
        roles = ["operator"]
    token, _ = main.auth_service.issue_token(actor, roles)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# TEST 1: AUTHORIZED ACCESS
# Valid token with correct role can access POST /validate
# ---------------------------------------------------------------------------
def test_1_authorized_access_post_validate(client, tmp_path):
    main.artifact_store.reports_dir = tmp_path
    headers = _make_auth_header(actor="cert-validator", roles=["operator"])
    payload = {
        "dataset_id": "api-certifiable",
        "dataset_path": str(ROOT / "datasets" / "certifiable_sample.csv"),
        "metadata_path": str(ROOT / "datasets" / "metadata.json"),
    }
    resp = client.post("/validate", json=payload, headers=headers)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["state"] == "VALIDATED"
    assert data["dataset_id"] == "api-certifiable"


# ---------------------------------------------------------------------------
# TEST 2: UNAUTHORIZED ACCESS
# Valid token but insufficient role gets DENY:INSUFFICIENT_ROLE on a role-protected endpoint
# ---------------------------------------------------------------------------
def test_2_unauthorized_access_insufficient_role(client):
    headers = _make_auth_header(actor="readonly-viewer", roles=["viewer"])
    payload = {
        "package_id": "pkg-dummy-promote",
        "to_status": "INGESTED",
        "actor": "readonly-viewer",
        "reason": "Unauthorized promotion attempt.",
    }
    resp = client.post("/packages/promote", json=payload, headers=headers)
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    assert "DENY:INSUFFICIENT_ROLE" in resp.text


# ---------------------------------------------------------------------------
# TEST 3: MISSING IDENTITY
# Request with no Bearer token to POST /certify returns 401/403 with DENY:MISSING_IDENTITY
# ---------------------------------------------------------------------------
def test_3_missing_identity_post_certify(client):
    payload = {"dataset_id": "api-certifiable"}
    resp = client.post("/certify", json=payload)
    assert resp.status_code in (401, 403), f"Expected 401 or 403, got {resp.status_code}"
    assert "DENY:MISSING_IDENTITY" in resp.text


# ---------------------------------------------------------------------------
# TEST 4: INVALID CREDENTIALS
# Malformed or expired token to POST /packages/register returns 401/403
# ---------------------------------------------------------------------------
def test_4_invalid_credentials_post_packages_register(client):
    headers = {"Authorization": "Bearer malformed.bogus.jwt-token"}
    payload = {
        "dataset_id": "ds-test-pkg",
        "dataset_version": "1.0.0",
        "schema_version": "2",
        "board": "AI",
        "medium": "text",
        "language": "en",
        "owner": "kavy",
        "actor": "test-actor",
        "reason": "Registration test",
    }
    resp = client.post("/packages/register", json=payload, headers=headers)
    assert resp.status_code in (401, 403), f"Expected 401 or 403, got {resp.status_code}"
    assert "DENY:INVALID_CREDENTIALS" in resp.text or "Invalid" in resp.text


# ---------------------------------------------------------------------------
# TEST 5: MISSING PERMISSIONS
# viewer role token attempting POST /packages/promote gets denied
# ---------------------------------------------------------------------------
def test_5_missing_permissions_viewer_promote_denied(client):
    headers = _make_auth_header(actor="plain-viewer", roles=["viewer", "dashboard-viewer"])
    payload = {
        "package_id": "pkg-test-promote-123",
        "to_status": "INGESTED",
        "actor": "plain-viewer",
        "reason": "Attempting promotion with viewer token.",
    }
    resp = client.post("/packages/promote", json=payload, headers=headers)
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"
    assert "DENY:INSUFFICIENT_ROLE" in resp.text


# ---------------------------------------------------------------------------
# TEST 6: FORGED ROLE CLAIMS
# Token issued with viewer/operator role but request body contains actor claiming admin
# verify identity.actor is used, not request body actor
# ---------------------------------------------------------------------------
def test_6_forged_role_claims_uses_identity_actor(client):
    headers = _make_auth_header(actor="legit-operator", roles=["operator"])
    payload = {
        "dataset_id": "ds-forged-claim-test",
        "dataset_version": "1.0.0",
        "schema_version": "2",
        "board": "AI",
        "medium": "text",
        "language": "en",
        "owner": "kavy",
        "actor": "spoofed-super-admin",  # Forged claim in payload
        "reason": "Verify identity binding",
    }
    resp = client.post("/packages/register", json=payload, headers=headers)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    # The recorded actor in history must match identity.actor, NOT the forged body.actor
    assert body["history"][0]["actor"] == "legit-operator"
    assert body["history"][0]["actor"] != "spoofed-super-admin"


# ---------------------------------------------------------------------------
# TEST 7: CONFLICTING POLICY
# actor=None passed internally to bcaes_registry._has_authority() returns False (not True as before FIX 2)
# ---------------------------------------------------------------------------
def test_7_conflicting_policy_bcaes_has_authority_none_fails_closed():
    # Even if admin role is provided in caller-supplied roles, None actor must DENY (False)
    result_with_roles = _has_authority(actor=None, actor_roles=["bhiv-admin", "admin"], boundaries=["Kavy"])
    assert result_with_roles is False, "Expected _has_authority(None, ...) to return False (fail-closed)"

    result_no_roles = _has_authority(actor=None, actor_roles=None, boundaries=["Kavy"])
    assert result_no_roles is False, "Expected _has_authority(None, None, ...) to return False"


# ---------------------------------------------------------------------------
# TEST 8: MALFORMED REQUEST
# Missing required fields plus no auth token — verify auth check fires before business logic
# ---------------------------------------------------------------------------
def test_8_malformed_request_auth_fires_before_validation(client):
    # Empty body with missing required fields: if validation ran first, this would be 422.
    # Because auth check fires first, it must return 401 with DENY:MISSING_IDENTITY.
    resp = client.post("/validate", json={})
    assert resp.status_code in (401, 403), f"Expected 401 or 403 auth denial, got {resp.status_code}"
    assert "DENY:MISSING_IDENTITY" in resp.text
    assert resp.status_code != 422, "Auth check should fire before request validation"


# ---------------------------------------------------------------------------
# TEST 9: UNAVAILABLE AUTH DEPENDENCY
# Simulate get_identity raising an exception — verify endpoint returns 403 not 500
# ---------------------------------------------------------------------------
def test_9_unavailable_auth_dependency_returns_403_not_500(client):
    def mock_failing_identity():
        raise PermissionError("DENY:AUTH_UNAVAILABLE")

    main.app.dependency_overrides[main.get_identity] = mock_failing_identity

    resp = client.post("/validate", json={"dataset_path": "dummy.csv"})
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    assert "DENY:AUTH_UNAVAILABLE" in resp.text
    assert resp.status_code != 500, "Auth dependency failure must not produce 500"


# ---------------------------------------------------------------------------
# TEST 10: BYPASS ATTEMPT
# Direct call to POST /pravah/events without token — verify DENY:MISSING_IDENTITY returned
# ---------------------------------------------------------------------------
def test_10_bypass_attempt_pravah_events_missing_token(client):
    payload = {
        "event_id": "evt-bypass-001",
        "entity_id": "pkg-bypass-001",
        "source_status": "NEW",
        "target_status": "VALIDATED",
        "producer": "anonymous-caller",
        "timestamp": 1700000000.0,
    }
    resp = client.post("/pravah/events", json=payload)
    assert resp.status_code in (401, 403), f"Expected 401 or 403, got {resp.status_code}"
    assert "DENY:MISSING_IDENTITY" in resp.text


# ---------------------------------------------------------------------------
# BONUS TEST 11: MISSING_ADMIN_PASSWORD escalation blocked (FIX 1)
# Verify that AUTH_PASSWORD alone cannot grant admin role when ADMIN_PASSWORD is unset
# ---------------------------------------------------------------------------
def test_11_missing_admin_password_escalation_blocked(client, monkeypatch):
    monkeypatch.setenv("AUTH_PASSWORD", "regular-auth-pass")
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    # Calling /auth/token attempting admin actor with standard password must be denied
    resp = client.post(
        "/auth/token",
        json={"actor": "kavy", "password": "regular-auth-pass"},
    )
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    assert "DENY:MISSING_ADMIN_PASSWORD" in resp.text

    # Also test AuthService directly fails closed
    svc = AuthService()
    with pytest.raises(AuthTokenError) as exc_info:
        svc.authenticate(actor="kavy", password="regular-auth-pass")
    assert "DENY:MISSING_ADMIN_PASSWORD" in str(exc_info.value)


# ---------------------------------------------------------------------------
# BONUS TEST 12: operational_sync with actor=None raises PermissionError (FIX 3)
# ---------------------------------------------------------------------------
def test_12_operational_sync_actor_none_raises_permission_error():
    with pytest.raises(PermissionError) as exc_info:
        _check(actor=None, actor_roles=["admin"], required_role="parikshak-sync")
    assert "DENY:MISSING_IDENTITY" in str(exc_info.value)
