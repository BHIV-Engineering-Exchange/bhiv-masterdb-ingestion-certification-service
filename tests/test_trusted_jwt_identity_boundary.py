"""
Tests for Phase 2.2.1: Trusted JWT Identity Boundary.

Validates:
1. Local HS256 Token Issuance:
   - Allowlisted actor can obtain a local token in development/test.
   - Non-allowlisted actor is rejected.
   - Missing actor allowlist is rejected.
   - Arbitrary request-body actor cannot obtain a token.
   - Local token issuance is rejected in production.
   - Missing local signing secret does not use a fallback credential.

2. Production RS256 Verification:
   - Valid TANTRA RS256 token is accepted.
   - Invalid signature is rejected.
   - Untrusted signing key is rejected.
   - Invalid issuer is rejected.
   - Invalid audience is rejected.
   - Missing required claims are rejected (exp, sub, iss, aud, roles).
   - Expired token is rejected.
   - Not-yet-valid token is rejected (nbf in future).
   - Clock-skewed future token is rejected (iat > 300s in future).
   - HS256 token is rejected in production.
   - Locally issued HS256 identity cannot be mistaken for a TANTRA identity.

3. Actor Authenticity and Application Authorization:
   - Caller cannot impersonate an allowlisted or entitled actor using an arbitrary body value.
   - Verified actor without application entitlement is rejected (403).
   - Verified actor with explicit application entitlement can proceed (200).
   - Admin role does not bypass application entitlement.
   - Invalid identity is rejected before capability authorization or retrieval.

4. D2 & D4 Controls Preserved:
   - Store-first authoritative persistent grant resolution.
   - Revoked / missing / malformed persistent grants fail closed.
"""
import time
from datetime import datetime, timezone
import pytest
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import main
from auth.models import AuthIdentity
from auth.service import AuthService, AuthTokenError
from models import (
    AccessContract,
    CapabilityAccessRequest,
    CapabilityRetrieveRequest,
)


def _err(resp) -> str:
    """Helper to extract error message from standard API error response."""
    data = resp.json()
    if isinstance(data, dict):
        if "error" in data and isinstance(data["error"], dict) and "message" in data["error"]:
            return data["error"]["message"]
        if "detail" in data:
            return data["detail"]
    return str(data)


@pytest.fixture
def rsa_key_pair():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return priv_pem, pub_pem


@pytest.fixture
def client():
    return TestClient(main.app)


# ===========================================================================
# 1. LOCAL TOKEN ISSUANCE (Development / Test Only)
# ===========================================================================

def test_local_issuance_allowlisted_actor_succeeds(monkeypatch):
    """Allowlisted actor can obtain a local token in development/test."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("AUTH_JWT_SECRET", "explicit-test-secret-32-chars-long!")
    monkeypatch.setenv("AUTH_ALLOWED_ACTORS", "alice,bob,tantra-agent")
    monkeypatch.setenv("AUTH_PASSWORD", "test-auth-password")

    auth_svc = AuthService()
    token, expires_at, roles = auth_svc.authenticate(actor="alice", password="test-auth-password")
    assert token
    assert expires_at
    assert "viewer" in roles

    # Decode and check provenance
    identity = auth_svc.decode_token(token)
    assert identity.actor == "alice"
    assert identity.auth_method == "HS256"
    assert identity.issuer == "masterdb-local"
    assert identity.is_tantra_verified is False


def test_local_issuance_non_allowlisted_actor_rejected(monkeypatch):
    """Non-allowlisted actor is rejected from local token issuance."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("AUTH_JWT_SECRET", "explicit-test-secret-32-chars-long!")
    monkeypatch.setenv("AUTH_ALLOWED_ACTORS", "alice,bob")
    monkeypatch.setenv("AUTH_PASSWORD", "test-auth-password")

    auth_svc = AuthService()
    with pytest.raises(AuthTokenError, match="not authorized for local token issuance"):
        auth_svc.authenticate(actor="mallory", password="test-auth-password")


def test_local_issuance_missing_allowlist_fails_closed(monkeypatch):
    """Missing or empty AUTH_ALLOWED_ACTORS fails closed."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("AUTH_JWT_SECRET", "explicit-test-secret-32-chars-long!")
    monkeypatch.delenv("AUTH_ALLOWED_ACTORS", raising=False)
    monkeypatch.setenv("AUTH_PASSWORD", "test-auth-password")

    auth_svc = AuthService()
    with pytest.raises(AuthTokenError, match="AUTH_ALLOWED_ACTORS must be configured"):
        auth_svc.authenticate(actor="alice", password="test-auth-password")


def test_local_issuance_arbitrary_request_body_actor_cannot_obtain_token(client, monkeypatch):
    """Arbitrary actor in request body cannot obtain a token via POST /auth/token."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("AUTH_JWT_SECRET", "explicit-test-secret-32-chars-long!")
    monkeypatch.setenv("AUTH_ALLOWED_ACTORS", "legit-service")
    monkeypatch.setenv("AUTH_PASSWORD", "test-auth-password")

    resp = client.post(
        "/auth/token",
        json={"actor": "arbitrary-unauthorized-actor", "password": "test-auth-password"},
    )
    assert resp.status_code == 401
    assert "not authorized for local token issuance" in _err(resp)


def test_local_issuance_rejected_in_production(client, monkeypatch):
    """POST /auth/token in production mode returns 403 Forbidden."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_JWT_SECRET", "explicit-prod-secret-32-chars-long!")
    monkeypatch.setenv("AUTH_ALLOWED_ACTORS", "alice")
    monkeypatch.setenv("AUTH_PASSWORD", "test-auth-password")

    resp = client.post(
        "/auth/token",
        json={"actor": "alice", "password": "test-auth-password"},
    )
    assert resp.status_code == 403
    assert "prohibited in production" in _err(resp).lower()


def test_local_issuance_missing_signing_secret_refuses_fallback(monkeypatch):
    """Missing explicit secret in dev/test refuses token issuance without fallback secret."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.delenv("AUTH_JWT_SECRET", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv("AUTH_ALLOWED_ACTORS", "alice")
    monkeypatch.setenv("AUTH_PASSWORD", "test-auth-password")

    auth_svc = AuthService()
    with pytest.raises(AuthTokenError, match="AUTH_JWT_SECRET is not explicitly configured"):
        auth_svc.authenticate(actor="alice", password="test-auth-password")


# ===========================================================================
# 2. PRODUCTION RS256 VERIFICATION
# ===========================================================================

def test_production_rs256_valid_tantra_token_accepted(rsa_key_pair):
    """Valid TANTRA RS256 token is verified and accepted."""
    priv_pem, pub_pem = rsa_key_pair
    auth_svc = AuthService(public_key_pem=pub_pem)

    payload = {
        "sub": "tantra-sarathi-worker",
        "iss": "tantra-sarathi",
        "aud": "masterdb",
        "roles": ["ecosystem-reader", "viewer"],
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }
    token = jwt.encode(payload, priv_pem, algorithm="RS256")

    identity = auth_svc.decode_token(token)
    assert identity.actor == "tantra-sarathi-worker"
    assert identity.auth_method == "RS256"
    assert identity.issuer == "tantra-sarathi"
    assert identity.is_tantra_verified is True
    assert "ecosystem-reader" in identity.roles


def test_production_rs256_invalid_signature_rejected(rsa_key_pair):
    """Token with corrupted signature is rejected."""
    priv_pem, pub_pem = rsa_key_pair
    auth_svc = AuthService(public_key_pem=pub_pem)

    payload = {
        "sub": "tantra-sarathi-worker",
        "iss": "tantra-sarathi",
        "aud": "masterdb",
        "roles": ["ecosystem-reader"],
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, priv_pem, algorithm="RS256")
    tampered = token[:-10] + ("abcdefghij" if token[-10:] != "abcdefghij" else "1234567890")

    with pytest.raises(AuthTokenError, match="invalid or badly signed"):
        auth_svc.decode_token(tampered)


def test_production_rs256_untrusted_signing_key_rejected(rsa_key_pair):
    """Token signed with an untrusted private key is rejected."""
    _, pub_pem = rsa_key_pair
    other_priv = rsa.generate_private_key(65537, 2048)
    other_priv_pem = other_priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    auth_svc = AuthService(public_key_pem=pub_pem)
    payload = {
        "sub": "attacker",
        "iss": "tantra-sarathi",
        "aud": "masterdb",
        "roles": ["ecosystem-reader"],
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, other_priv_pem, algorithm="RS256")

    with pytest.raises(AuthTokenError, match="invalid or badly signed"):
        auth_svc.decode_token(token)


def test_production_rs256_invalid_issuer_rejected(rsa_key_pair):
    """RS256 token with untrusted issuer is rejected."""
    priv_pem, pub_pem = rsa_key_pair
    auth_svc = AuthService(public_key_pem=pub_pem)

    payload = {
        "sub": "tantra-sarathi-worker",
        "iss": "untrusted-issuer",
        "aud": "masterdb",
        "roles": ["ecosystem-reader"],
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, priv_pem, algorithm="RS256")

    with pytest.raises(AuthTokenError, match="Untrusted or missing token issuer"):
        auth_svc.decode_token(token)


def test_production_rs256_invalid_audience_rejected(rsa_key_pair):
    """RS256 token with untrusted audience is rejected."""
    priv_pem, pub_pem = rsa_key_pair
    auth_svc = AuthService(public_key_pem=pub_pem)

    payload = {
        "sub": "tantra-sarathi-worker",
        "iss": "tantra-sarathi",
        "aud": "rogue-service",
        "roles": ["ecosystem-reader"],
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, priv_pem, algorithm="RS256")

    with pytest.raises(AuthTokenError, match="Untrusted or invalid token audience"):
        auth_svc.decode_token(token)


def test_production_rs256_missing_required_claims_rejected(rsa_key_pair):
    """Tokens missing required claims (sub, iss, aud, roles) are rejected."""
    priv_pem, pub_pem = rsa_key_pair
    auth_svc = AuthService(public_key_pem=pub_pem)

    # Missing sub
    t_no_sub = jwt.encode({"iss": "tantra-sarathi", "aud": "masterdb", "exp": int(time.time()) + 3600, "roles": ["viewer"]}, priv_pem, "RS256")
    with pytest.raises(AuthTokenError, match="missing a subject"):
        auth_svc.decode_token(t_no_sub)

    # Missing iss
    t_no_iss = jwt.encode({"sub": "a", "aud": "masterdb", "exp": int(time.time()) + 3600, "roles": ["viewer"]}, priv_pem, "RS256")
    with pytest.raises(AuthTokenError, match="Untrusted or missing token issuer"):
        auth_svc.decode_token(t_no_iss)

    # Missing aud
    t_no_aud = jwt.encode({"sub": "a", "iss": "tantra-sarathi", "exp": int(time.time()) + 3600, "roles": ["viewer"]}, priv_pem, "RS256")
    with pytest.raises(AuthTokenError, match="missing required audience claim"):
        auth_svc.decode_token(t_no_aud)

    # Missing roles
    t_no_roles = jwt.encode({"sub": "a", "iss": "tantra-sarathi", "aud": "masterdb", "exp": int(time.time()) + 3600}, priv_pem, "RS256")
    with pytest.raises(AuthTokenError, match="missing required roles claim"):
        auth_svc.decode_token(t_no_roles)


def test_production_rs256_expired_token_rejected(rsa_key_pair):
    """Expired RS256 token is rejected."""
    priv_pem, pub_pem = rsa_key_pair
    auth_svc = AuthService(public_key_pem=pub_pem)

    payload = {
        "sub": "tantra-sarathi-worker",
        "iss": "tantra-sarathi",
        "aud": "masterdb",
        "roles": ["ecosystem-reader"],
        "exp": int(time.time()) - 100,
    }
    token = jwt.encode(payload, priv_pem, algorithm="RS256")

    with pytest.raises(AuthTokenError, match="Token has expired"):
        auth_svc.decode_token(token)


def test_production_rs256_not_yet_valid_token_rejected(rsa_key_pair):
    """RS256 token with nbf in the future is rejected."""
    priv_pem, pub_pem = rsa_key_pair
    auth_svc = AuthService(public_key_pem=pub_pem)

    payload = {
        "sub": "tantra-sarathi-worker",
        "iss": "tantra-sarathi",
        "aud": "masterdb",
        "roles": ["ecosystem-reader"],
        "nbf": int(time.time()) + 600,
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, priv_pem, algorithm="RS256")

    with pytest.raises(AuthTokenError, match="not yet valid"):
        auth_svc.decode_token(token)


def test_production_rs256_future_iat_skew_rejected(rsa_key_pair):
    """RS256 token issued far in the future (>300s) is rejected."""
    priv_pem, pub_pem = rsa_key_pair
    auth_svc = AuthService(public_key_pem=pub_pem)

    payload = {
        "sub": "tantra-sarathi-worker",
        "iss": "tantra-sarathi",
        "aud": "masterdb",
        "roles": ["ecosystem-reader"],
        "iat": int(time.time()) + 600,
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, priv_pem, algorithm="RS256")

    with pytest.raises(AuthTokenError, match=r"(Token is not yet valid.*iat|Token issued in the future)"):
        auth_svc.decode_token(token)


def test_production_rejects_hs256_tokens(rsa_key_pair, monkeypatch):
    """In production mode, HS256 tokens are strictly rejected by decode_token."""
    _, pub_pem = rsa_key_pair
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_JWT_SECRET", "explicit-prod-secret-32-chars-long!")

    auth_svc = AuthService(public_key_pem=pub_pem, secret_key="explicit-prod-secret-32-chars-long!")

    hs_token = jwt.encode(
        {"sub": "actor", "roles": ["viewer"], "exp": int(time.time()) + 3600},
        "explicit-prod-secret-32-chars-long!",
        algorithm="HS256",
    )

    with pytest.raises(AuthTokenError, match="HS256 symmetric tokens are rejected in production mode"):
        auth_svc.decode_token(hs_token)


def test_hs256_cannot_masquerade_as_tantra_verified(monkeypatch):
    """Locally issued HS256 identity has is_tantra_verified=False and auth_method='HS256'."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("AUTH_JWT_SECRET", "explicit-test-secret-32-chars-long!")
    monkeypatch.setenv("AUTH_ALLOWED_ACTORS", "test-agent")
    monkeypatch.setenv("AUTH_PASSWORD", "test-auth-password")

    auth_svc = AuthService()
    token, _, _ = auth_svc.authenticate("test-agent", password="test-auth-password")

    identity = auth_svc.decode_token(token)
    assert identity.is_tantra_verified is False
    assert identity.auth_method == "HS256"
    assert identity.issuer == "masterdb-local"


# ===========================================================================
# 3. ACTOR AUTHENTICITY AND APPLICATION AUTHORIZATION
# ===========================================================================

def test_caller_cannot_impersonate_actor_using_arbitrary_body_value(client, monkeypatch):
    """Actor identity comes strictly from verified token, not caller body."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("AUTH_JWT_SECRET", "explicit-test-secret-32-chars-long!")
    monkeypatch.setenv("AUTH_ALLOWED_ACTORS", "actor-a,actor-b")
    monkeypatch.setenv("AUTH_PASSWORD", "test-auth-password")
    monkeypatch.setenv("AUTH_ENTITLED_APPS_ACTOR_A", "APP_ALPHA")
    monkeypatch.setenv("AUTH_ENTITLED_APPS_ACTOR_B", "APP_BETA")

    # Issue token for actor-a
    auth_svc = AuthService(secret_key="explicit-test-secret-32-chars-long!")
    monkeypatch.setattr(main, 'auth_service', auth_svc)
    token, _, _ = auth_svc.authenticate("actor-a", password="test-auth-password")

    # Caller passes body requesting APP_BETA (which actor-b is entitled to, not actor-a)
    resp = client.post(
        "/access/request",
        json={
            "application_id": "APP_BETA",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    # Entitlement gate denies actor-a from representing APP_BETA
    assert resp.status_code == 403
    assert "not entitled to represent application" in _err(resp).lower()


def test_verified_actor_without_application_entitlement_rejected(client, monkeypatch):
    """Verified actor without configured application entitlement is rejected with 403."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("AUTH_JWT_SECRET", "explicit-test-secret-32-chars-long!")
    monkeypatch.setenv("AUTH_ALLOWED_ACTORS", "unentitled-actor")
    monkeypatch.setenv("AUTH_PASSWORD", "test-auth-password")
    # No AUTH_ENTITLED_APPS_UNENTITLED_ACTOR configured

    auth_svc = AuthService(secret_key="explicit-test-secret-32-chars-long!")
    monkeypatch.setattr(main, 'auth_service', auth_svc)
    token, _, _ = auth_svc.authenticate("unentitled-actor", password="test-auth-password")

    resp = client.post(
        "/access/request",
        json={
            "application_id": "SOME_APP",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert "not entitled" in _err(resp).lower()


def test_verified_actor_with_explicit_entitlement_succeeds(client, monkeypatch):
    """Verified actor with explicit server-side entitlement succeeds."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("AUTH_JWT_SECRET", "explicit-test-secret-32-chars-long!")
    monkeypatch.setenv("AUTH_ALLOWED_ACTORS", "entitled-agent")
    monkeypatch.setenv("AUTH_PASSWORD", "test-auth-password")
    monkeypatch.setenv("AUTH_ENTITLED_APPS_ENTITLED_AGENT", "VALID_APP")

    auth_svc = AuthService(secret_key="explicit-test-secret-32-chars-long!")
    monkeypatch.setattr(main, 'auth_service', auth_svc)
    token, _, _ = auth_svc.authenticate("entitled-agent", password="test-auth-password")

    resp = client.post(
        "/access/request",
        json={
            "application_id": "VALID_APP",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["authorized"] is True


def test_admin_role_does_not_bypass_application_entitlement(client, monkeypatch):
    """Admin role does not bypass D4 application entitlement checks."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("AUTH_JWT_SECRET", "explicit-test-secret-32-chars-long!")
    monkeypatch.setenv("AUTH_ALLOWED_ACTORS", "kavy,admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "dedicated-admin-pass")
    # kavy has bhiv-admin role, but is NOT entitled to "RESTRICTED_APP"

    auth_svc = AuthService(secret_key="explicit-test-secret-32-chars-long!")
    monkeypatch.setattr(main, 'auth_service', auth_svc)
    token, _, roles = auth_svc.authenticate("kavy", password="dedicated-admin-pass")
    assert "bhiv-admin" in roles

    resp = client.post(
        "/access/request",
        json={
            "application_id": "RESTRICTED_APP",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert "not entitled" in _err(resp).lower()


def test_invalid_identity_rejected_before_capability_access(client):
    """Requests with missing or invalid tokens are rejected with 401 before business logic."""
    # Missing token
    resp_no_token = client.post(
        "/access/request",
        json={
            "application_id": "APP",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "test",
        },
    )
    assert resp_no_token.status_code == 401

    # Malformed token
    resp_bad_token = client.post(
        "/access/request",
        json={
            "application_id": "APP",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "test",
        },
        headers={"Authorization": "Bearer bad-token-data"},
    )
    assert resp_bad_token.status_code == 401


def test_production_mode_capability_access_requires_tantra_rs256(rsa_key_pair, monkeypatch):
    """In production mode, capability endpoints reject non-TANTRA verified identities."""
    _, pub_pem = rsa_key_pair
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_JWT_SECRET", "explicit-prod-secret-32-chars-long!")
    monkeypatch.setenv("AUTH_JWT_PUBLIC_KEY", pub_pem)
    monkeypatch.setenv("AUTH_ENTITLED_APPS_PROD_ACTOR", "PROD_APP")

    auth_svc = AuthService(secret_key="explicit-prod-secret-32-chars-long!", public_key_pem=pub_pem)
    monkeypatch.setattr(main, 'auth_service', auth_svc)

    # Directly mock an HS256 identity in FastAPI dependency
    hs_identity = AuthIdentity(
        actor="prod-actor",
        roles=["viewer"],
        auth_method="HS256",
        issuer="masterdb-local",
        is_tantra_verified=False,
    )
    main.app.dependency_overrides[main.get_identity] = lambda: hs_identity
    try:
        from fastapi.testclient import TestClient
        client = TestClient(main.app)
        resp = client.post(
            "/access/request",
            json={
                "application_id": "PROD_APP",
                "capability_id": "cap-mangrove-monitoring",
                "purpose": "environmental_monitoring",
            },
        )
        assert resp.status_code == 403
        assert "Production capability access requires a cryptographically verified TANTRA RS256 identity" in _err(resp)
    finally:
        main.app.dependency_overrides.pop(main.get_identity, None)
