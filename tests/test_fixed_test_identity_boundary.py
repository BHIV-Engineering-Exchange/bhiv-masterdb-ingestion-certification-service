"""
Tests for Phase 2.2.3: Option B Fixed Test-Only JWT Identity Boundary.

Verifies:
1. Fixed test token authenticates through the normal Bearer JWT path.
2. Fixed test token has the expected actor and roles.
3. Token signed with the test key is rejected in production mode.
4. Test token cannot authenticate as a different actor.
5. Unknown test actor is rejected by D4 entitlement checks.
6. Test tokens / test issuer cannot be used to create production identity trust.
7. Capability access succeeds with fixed test tokens without calling /auth/token.
8. D2 persistent grant resolution and D4 application entitlement remain enforced.
"""
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import main
from auth.service import AuthService, AuthTokenError
from tests.test_identity_fixtures import (
    TEST_RSA_PRIVATE_KEY_PEM,
    TEST_RSA_PUBLIC_KEY_PEM,
    TEST_TOKEN_ISSUER,
    get_test_token,
    get_test_auth_headers,
    issue_fixed_test_token,
)


@pytest.fixture
def client():
    return TestClient(main.app)


def _err(resp) -> str:
    """Helper to extract error message from standard API error response."""
    data = resp.json()
    if isinstance(data, dict):
        if "error" in data and isinstance(data["error"], dict) and "message" in data["error"]:
            return data["error"]["message"]
        if "detail" in data:
            return data["detail"]
    return str(data)


# -----------------------------------------------------------------------------
# 1. FIXED TEST TOKEN AUTHENTICATION VIA NORMAL BEARER PATH
# -----------------------------------------------------------------------------

def test_fixed_test_token_authenticates_through_bearer_path(client):
    """Proves a fixed pre-issued test token authenticates through normal Bearer JWT dependency."""
    headers = get_test_auth_headers("test-app")
    resp = client.get("/capabilities", headers=headers)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    assert isinstance(resp.json(), list)


def test_fixed_test_token_has_expected_actor_and_roles():
    """Proves a fixed test token resolves to the exact expected actor and server-side test roles."""
    auth_svc = AuthService(public_key_pem=TEST_RSA_PUBLIC_KEY_PEM)
    
    # Standard consumer actor
    consumer_token = get_test_token("VALID_CONSUMER")
    identity = auth_svc.decode_token(consumer_token)
    assert identity.actor == "VALID_CONSUMER"
    assert "ecosystem-reader" in identity.roles
    assert identity.auth_method == "RS256"
    assert identity.is_tantra_verified is True
    assert identity.issuer == TEST_TOKEN_ISSUER

    # Administrative actor
    admin_token = get_test_token("admin")
    admin_identity = auth_svc.decode_token(admin_token)
    assert admin_identity.actor == "admin"
    assert "bhiv-admin" in admin_identity.roles
    assert "admin" in admin_identity.roles
    assert admin_identity.auth_method == "RS256"


# -----------------------------------------------------------------------------
# 2. PRODUCTION REJECTION OF TEST TOKENS & TEST ISSUER
# -----------------------------------------------------------------------------

def test_token_signed_with_test_key_rejected_in_production_mode(monkeypatch):
    """A token signed with the test key is rejected when production mode is active."""
    # Generate an independent real production RSA key pair
    prod_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    prod_pub_pem = prod_priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_JWT_PUBLIC_KEY", prod_pub_pem)
    monkeypatch.setenv("AUTH_JWT_SECRET", "production-mandatory-secret-32-chars-long!!")
    monkeypatch.delenv("AUTH_ISSUER", raising=False)

    auth_svc = AuthService()
    assert auth_svc.is_production is True

    test_token = get_test_token("VALID_CONSUMER")
    with pytest.raises(AuthTokenError, match="Token is invalid or badly signed"):
        auth_svc.decode_token(test_token)


def test_test_tokens_cannot_create_production_identity_trust(monkeypatch):
    """Test issuer 'masterdb-test-fixture' is strictly prohibited in production mode even if misconfigured."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    # Even if an attacker or misconfiguration injects the test public key and test issuer into prod environment
    monkeypatch.setenv("AUTH_JWT_PUBLIC_KEY", TEST_RSA_PUBLIC_KEY_PEM)
    monkeypatch.setenv("AUTH_ISSUER", TEST_TOKEN_ISSUER)
    monkeypatch.setenv("AUTH_JWT_SECRET", "production-mandatory-secret-32-chars-long!!")

    auth_svc = AuthService()
    assert auth_svc.is_production is True

    test_token = get_test_token("VALID_CONSUMER")
    with pytest.raises(AuthTokenError, match="Test token issuer 'masterdb-test-fixture' is prohibited in production mode"):
        auth_svc.decode_token(test_token)


def test_production_rejects_test_signature_with_forged_tantra_issuer(monkeypatch):
    """Even if a test token attempts to claim 'iss: tantra-sarathi', signature verification against production key fails."""
    prod_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    prod_pub_pem = prod_priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_JWT_PUBLIC_KEY", prod_pub_pem)
    monkeypatch.setenv("AUTH_JWT_SECRET", "production-mandatory-secret-32-chars-long!!")

    auth_svc = AuthService()
    # Sign token with test key but forge issuer to "tantra-sarathi"
    forged_token = issue_fixed_test_token(actor="attacker", issuer="tantra-sarathi")

    with pytest.raises(AuthTokenError, match="Token is invalid or badly signed: Signature verification failed"):
        auth_svc.decode_token(forged_token)


# -----------------------------------------------------------------------------
# 3. ACTOR BOUNDARY & D4 ENTITLEMENT ENFORCEMENT
# -----------------------------------------------------------------------------

def test_test_token_cannot_authenticate_as_different_actor(client, monkeypatch):
    """A test token issued for 'auth-tester' cannot claim application entitled to 'VALID_CONSUMER'."""
    monkeypatch.setenv("AUTH_ENTITLED_APPS_VALID_CONSUMER", "VALID_CONSUMER")
    monkeypatch.setenv("AUTH_ENTITLED_APPS_AUTH_TESTER", "OTHER_APP")

    headers = get_test_auth_headers("auth-tester")
    resp = client.post(
        "/access/request",
        json={
            "application_id": "VALID_CONSUMER",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers=headers,
    )
    assert resp.status_code == 403
    assert "not entitled to represent application" in _err(resp)


def test_unknown_test_actor_rejected(client):
    """An unknown test actor without server-side application entitlement is rejected (403)."""
    headers = get_test_auth_headers("unknown-test-actor")
    resp = client.post(
        "/access/request",
        json={
            "application_id": "UNAUTHORIZED_APP",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers=headers,
    )
    assert resp.status_code == 403
    assert "not entitled to represent application" in _err(resp)


def test_valid_test_token_with_explicit_entitlement_succeeds(client, monkeypatch):
    """A verified test token matching explicit server-side entitlement succeeds without calling /auth/token."""
    monkeypatch.setenv("AUTH_ENTITLED_APPS_VALID_CONSUMER", "VALID_CONSUMER")

    headers = get_test_auth_headers("VALID_CONSUMER")
    resp = client.post(
        "/access/request",
        json={
            "application_id": "VALID_CONSUMER",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    grant = resp.json()
    assert grant["authorized"] is True
    assert grant["application_id"] == "VALID_CONSUMER"
    assert grant["access_token"].startswith("grant-")


# -----------------------------------------------------------------------------
# 4. INDEPENDENCE FROM /auth/token ENDPOINT
# -----------------------------------------------------------------------------

def test_capability_flow_independent_of_auth_token_endpoint(client, monkeypatch):
    """Proves automated capability flow operates completely independent of /auth/token."""
    # Even if /auth/token is disabled or unreachable, fixed test token succeeds
    headers = get_test_auth_headers("DATA_CONSUMER", ["ecosystem-reader", "viewer"])
    monkeypatch.setenv("AUTH_ENTITLED_APPS_DATA_CONSUMER", "DATA_CONSUMER")

    # 1. Request access
    access_resp = client.post(
        "/access/request",
        json={
            "application_id": "DATA_CONSUMER",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers=headers,
    )
    assert access_resp.status_code == 200
    grant = access_resp.json()
    access_token = grant["access_token"]

    # 2. Retrieve data
    ret_resp = client.post(
        "/capabilities/cap-mangrove-monitoring/retrieve",
        json={
            "application_id": "DATA_CONSUMER",
            "access_token": access_token,
        },
        headers=headers,
    )
    assert ret_resp.status_code == 200
    data = ret_resp.json()
    assert data["capability"]["capability_id"] == "cap-mangrove-monitoring"
    assert "data" in data
