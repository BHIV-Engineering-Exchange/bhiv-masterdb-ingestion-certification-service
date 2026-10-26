"""
Authentication and JWT Security Hardening Regression Tests.
Covers findings F-AUTH-01 through F-AUTH-04:
1. All supported password environment variables unset: token issuance fails closed.
2. Incorrect password: no token is issued.
3. Correct configured credentials: expected existing supported flow works.
4. Supplying admin, bhiv-admin, ops, or kavy as an actor cannot independently grant privileged roles.
5. Caller-supplied roles cannot override server-side authorization.
6. Production startup without a stable JWT secret fails safely.
7. A stable configured secret supports verification across independently initialized application/auth instances.
8. Missing, malformed, expired, unsigned, or incorrectly signed tokens are rejected.
9. A forged token with another actor's sub cannot select or exhaust that actor's rate-limit identity.
10. Rate limiting continues to work for legitimate authenticated requests.
11. Existing authentication and authorization tests remain valid.
"""
import time
import jwt
import pytest
from fastapi.testclient import TestClient

import main
from auth.service import AuthService, AuthTokenError


@pytest.fixture
def client():
    return TestClient(main.app)


# ---------------------------------------------------------------------------
# 1. F-AUTH-01: Password unconfigured fails closed
# ---------------------------------------------------------------------------
def test_all_password_env_vars_unset_fails_closed(client, monkeypatch):
    monkeypatch.delenv("AUTH_PASSWORD", raising=False)
    monkeypatch.delenv("MASTERDB_AUTH_PASSWORD", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    # Calling /auth/token with or without password must fail 401 closed
    resp_no_pw = client.post("/auth/token", json={"actor": "test-user"})
    assert resp_no_pw.status_code == 401
    assert "not configured" in resp_no_pw.json()["error"]["message"]

    resp_with_pw = client.post(
        "/auth/token", json={"actor": "test-user", "password": "arbitrary-password"}
    )
    assert resp_with_pw.status_code == 401
    assert "not configured" in resp_with_pw.json()["error"]["message"]


def test_public_token_endpoint_rejects_privileged_actor_without_password(client, monkeypatch):
    monkeypatch.delenv("AUTH_PASSWORD", raising=False)
    monkeypatch.delenv("MASTERDB_AUTH_PASSWORD", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    resp = client.post("/auth/token", json={"actor": "kavy", "roles": ["viewer"]})
    assert resp.status_code == 401
    assert "configured server authentication password" in resp.json()["error"]["message"]


def test_public_token_endpoint_invalid_credentials_returns_401(client, monkeypatch):
    monkeypatch.setenv("AUTH_PASSWORD", "secret123")
    resp = client.post("/auth/token", json={"actor": "kavy", "password": "wrongpassword"})
    assert resp.status_code == 401
    assert "Invalid credentials" in resp.json()["error"]["message"]


# ---------------------------------------------------------------------------
# 2. Incorrect password: no token issued
# ---------------------------------------------------------------------------
def test_incorrect_password_rejects_issuance(client, monkeypatch):
    monkeypatch.setenv("AUTH_PASSWORD", "correct-secret-123")
    resp = client.post(
        "/auth/token", json={"actor": "test-user", "password": "wrong-secret-999"}
    )
    assert resp.status_code == 401
    assert "Invalid credentials" in resp.json()["error"]["message"]


# ---------------------------------------------------------------------------
# 3. Correct configured credentials: works as expected
# ---------------------------------------------------------------------------
def test_correct_configured_credentials_issues_token(client, monkeypatch):
    monkeypatch.setenv("AUTH_PASSWORD", "correct-secret-123")
    resp = client.post(
        "/auth/token", json={"actor": "legit-user", "password": "correct-secret-123"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["actor"] == "legit-user"
    assert data["roles"] == ["viewer", "dashboard-viewer"]

    identity = main.auth_service.decode_token(data["access_token"])
    assert identity.actor == "legit-user"


def test_supported_password_env_aliases_work(client, monkeypatch):
    # Test MASTERDB_AUTH_PASSWORD alias
    monkeypatch.delenv("AUTH_PASSWORD", raising=False)
    monkeypatch.setenv("MASTERDB_AUTH_PASSWORD", "alias-secret")
    resp = client.post(
        "/auth/token", json={"actor": "alias-user", "password": "alias-secret"}
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


# ---------------------------------------------------------------------------
# 4. F-AUTH-02: Supplying admin/bhiv-admin/ops/kavy cannot independently grant privileged roles
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("privileged_actor", ["admin", "bhiv-admin", "ops", "kavy"])
def test_actor_name_cannot_independently_grant_privileged_roles(
    client, monkeypatch, privileged_actor
):
    monkeypatch.setenv("AUTH_PASSWORD", "shared-user-pass")
    resp = client.post(
        "/auth/token",
        json={"actor": privileged_actor, "password": "shared-user-pass"},
    )
    assert resp.status_code == 200
    roles = resp.json()["roles"]
    assert "bhiv-admin" not in roles, f"Actor {privileged_actor} escalated to bhiv-admin"
    assert "admin" not in roles, f"Actor {privileged_actor} escalated to admin"
    assert "operator" not in roles, f"Actor {privileged_actor} escalated to operator"
    assert roles == ["viewer", "dashboard-viewer"]


# ---------------------------------------------------------------------------
# 5. Caller-supplied roles cannot override server-side authorization
# ---------------------------------------------------------------------------
def test_caller_supplied_roles_cannot_override_authorization(client, monkeypatch):
    monkeypatch.setenv("AUTH_PASSWORD", "shared-user-pass")
    resp = client.post(
        "/auth/token",
        json={
            "actor": "attacker",
            "password": "shared-user-pass",
            "roles": ["bhiv-admin", "admin", "operator", "root"],
        },
    )
    assert resp.status_code == 200
    roles = resp.json()["roles"]
    assert "bhiv-admin" not in roles
    assert "admin" not in roles
    assert "operator" not in roles
    assert "root" not in roles
    assert roles == ["viewer", "dashboard-viewer"]

    identity = main.auth_service.decode_token(resp.json()["access_token"])
    assert "bhiv-admin" not in identity.roles


def test_verified_admin_credentials_grant_admin_roles(client, monkeypatch):
    monkeypatch.setenv("AUTH_PASSWORD", "standard-pass")
    monkeypatch.setenv("ADMIN_PASSWORD", "dedicated-admin-pass")

    # Caller with standard password gets standard roles
    user_resp = client.post(
        "/auth/token", json={"actor": "ops", "password": "standard-pass"}
    )
    assert user_resp.status_code == 200
    assert user_resp.json()["roles"] == ["viewer", "dashboard-viewer"]

    # Caller with dedicated admin password gets admin roles
    admin_resp = client.post(
        "/auth/token", json={"actor": "ops", "password": "dedicated-admin-pass"}
    )
    assert admin_resp.status_code == 200
    assert "bhiv-admin" in admin_resp.json()["roles"]
    assert "admin" in admin_resp.json()["roles"]


# ---------------------------------------------------------------------------
# 6. F-AUTH-03: Production startup without stable JWT secret fails safely
# ---------------------------------------------------------------------------
def test_production_startup_without_jwt_secret_fails_safely(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("AUTH_JWT_SECRET", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError) as exc_info:
        AuthService()
    assert "AUTH_JWT_SECRET must be configured in production" in str(exc_info.value)


def test_production_startup_with_empty_secret_fails_safely(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_JWT_SECRET", "   ")
    with pytest.raises(RuntimeError) as exc_info:
        AuthService()
    assert "AUTH_JWT_SECRET must be configured in production" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 7. Stable configured secret supports multi-worker verification
# ---------------------------------------------------------------------------
def test_stable_secret_supports_multi_worker_verification():
    shared_secret = "stable-production-secret-configured-identically-across-workers"
    worker_1 = AuthService(secret_key=shared_secret)
    worker_2 = AuthService(secret_key=shared_secret)

    token, _ = worker_1.issue_token("distributed-actor", ["viewer"])
    identity = worker_2.decode_token(token)
    assert identity.actor == "distributed-actor"
    assert identity.roles == ["viewer"]


# ---------------------------------------------------------------------------
# 8. Missing, malformed, expired, unsigned, incorrectly-signed tokens rejected
# ---------------------------------------------------------------------------
def test_missing_token_rejected_on_protected_endpoint(client):
    resp = client.get("/databases")
    assert resp.status_code == 401


def test_malformed_token_rejected(client):
    resp = client.get("/databases", headers={"Authorization": "Bearer not-a-valid-token"})
    assert resp.status_code == 401


def test_expired_token_rejected():
    svc = AuthService(secret_key="test-key", expiry_minutes=0)
    token, _ = svc.issue_token("test-actor", [])
    time.sleep(1.1)
    with pytest.raises(AuthTokenError) as exc:
        svc.decode_token(token)
    assert "expired" in str(exc.value).lower()


def test_unsigned_or_none_algorithm_token_rejected():
    svc = AuthService(secret_key="test-key")
    unsigned_token = jwt.encode({"sub": "actor", "roles": []}, key="", algorithm="none")
    with pytest.raises(AuthTokenError):
        svc.decode_token(unsigned_token)


def test_incorrectly_signed_token_rejected():
    issuer_wrong = AuthService(secret_key="attacker-secret")
    verifier = AuthService(secret_key="server-secret")
    token, _ = issuer_wrong.issue_token("spoofed-actor", ["bhiv-admin"])
    with pytest.raises(AuthTokenError) as exc:
        verifier.decode_token(token)
    assert "invalid or badly signed" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# 9. F-AUTH-04: Forged token cannot select or exhaust another actor's rate limit
# ---------------------------------------------------------------------------
def test_forged_token_cannot_exhaust_victim_rate_limit(client):
    main.rate_limiter.reset()
    original_max = main.rate_limiter.max_requests
    main.rate_limiter.max_requests = 2
    try:
        # Attacker creates forged token claiming sub="victim-account" signed with bogus secret
        forged_payload = {"sub": "victim-account", "roles": [], "exp": int(time.time()) + 3600}
        forged_token = jwt.encode(forged_payload, "bogus-attacker-key", algorithm="HS256")
        attacker_headers = {"Authorization": f"Bearer {forged_token}"}

        # Attacker exhausts requests
        r1 = client.get("/canonical-repository/documents", headers=attacker_headers)
        r2 = client.get("/canonical-repository/documents", headers=attacker_headers)
        r3 = client.get("/canonical-repository/documents", headers=attacker_headers)
        # The unverified token fell back to IP keying, so attacker IP hit 429
        assert r3.status_code == 429

        # Now victim authenticates legitimately
        victim_token, _ = main.auth_service.issue_token("victim-account", [])
        victim_headers = {"Authorization": f"Bearer {victim_token}"}

        # Since victim's token has verified signature, its key is actor:victim-account (not the IP key)
        victim_resp = client.get("/canonical-repository/documents", headers=victim_headers)
        assert victim_resp.status_code == 200
    finally:
        main.rate_limiter.max_requests = original_max
        main.rate_limiter.reset()


# ---------------------------------------------------------------------------
# 10. Rate limiting continues to work for legitimate authenticated requests
# ---------------------------------------------------------------------------
def test_rate_limiting_works_for_legitimate_authenticated_requests(client):
    main.rate_limiter.reset()
    original_max = main.rate_limiter.max_requests
    main.rate_limiter.max_requests = 2
    try:
        legit_token, _ = main.auth_service.issue_token("legit-actor", [])
        headers = {"Authorization": f"Bearer {legit_token}"}

        r1 = client.get("/canonical-repository/documents", headers=headers)
        assert r1.status_code == 200
        r2 = client.get("/canonical-repository/documents", headers=headers)
        assert r2.status_code == 200
        r3 = client.get("/canonical-repository/documents", headers=headers)
        assert r3.status_code == 429
        assert "retry_after_seconds" in r3.json()
    finally:
        main.rate_limiter.max_requests = original_max
        main.rate_limiter.reset()


# ---------------------------------------------------------------------------
# 11. Option A: RS256 Asymmetric Token Authentication (Sarathi Option A)
# ---------------------------------------------------------------------------
def test_rs256_asymmetric_token_verification_success():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    from auth.service import AuthService

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    auth_svc = AuthService(secret_key="test-secret", public_key_pem=public_pem)
    payload = {
        "sub": "tantra-execution-worker",
        "roles": ["ecosystem-reader", "operator"],
        "iss": "tantra-sarathi",
        "aud": "tantra-bridge",
        "jti": "jti-12345",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
        "trace_id": "trace-uuid-1",
        "execution_id": "exec-uuid-1",
    }
    token = jwt.encode(payload, private_pem, algorithm="RS256")
    identity = auth_svc.decode_token(token)

    assert identity.actor == "tantra-execution-worker"
    assert "ecosystem-reader" in identity.roles
    assert "operator" in identity.roles


def test_rs256_asymmetric_token_invalid_signature_rejected():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    from auth.service import AuthService, AuthTokenError

    key1 = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key2 = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    public_pem = key1.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    other_private_pem = key2.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    auth_svc = AuthService(secret_key="test-secret", public_key_pem=public_pem)
    payload = {
        "sub": "tantra-execution-worker",
        "iss": "tantra-sarathi",
        "aud": "masterdb",
        "exp": int(time.time()) + 3600,
    }
    forged_token = jwt.encode(payload, other_private_pem, algorithm="RS256")

    with pytest.raises(AuthTokenError, match="invalid or badly signed"):
        auth_svc.decode_token(forged_token)


def test_rs256_asymmetric_token_untrusted_issuer_rejected():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    from auth.service import AuthService, AuthTokenError

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    auth_svc = AuthService(secret_key="test-secret", public_key_pem=public_pem)
    payload = {
        "sub": "unauthorized-actor",
        "iss": "evil-untrusted-issuer",
        "aud": "masterdb",
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, private_pem, algorithm="RS256")

    with pytest.raises(AuthTokenError, match="Untrusted or missing token issuer"):
        auth_svc.decode_token(token)


def test_rs256_asymmetric_token_untrusted_audience_rejected():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    from auth.service import AuthService, AuthTokenError

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    auth_svc = AuthService(secret_key="test-secret", public_key_pem=public_pem)
    payload = {
        "sub": "tantra-execution-worker",
        "iss": "tantra-sarathi",
        "aud": "unauthorized-audience",
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, private_pem, algorithm="RS256")

    with pytest.raises(AuthTokenError, match="Untrusted or invalid token audience"):
        auth_svc.decode_token(token)


def test_rs256_asymmetric_token_missing_audience_rejected():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    from auth.service import AuthService, AuthTokenError

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    auth_svc = AuthService(secret_key="test-secret", public_key_pem=public_pem)
    payload = {
        "sub": "tantra-execution-worker",
        "iss": "tantra-sarathi",
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, private_pem, algorithm="RS256")

    with pytest.raises(AuthTokenError, match="Token is missing required audience claim"):
        auth_svc.decode_token(token)


def test_rs256_asymmetric_token_missing_issuer_rejected():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    from auth.service import AuthService, AuthTokenError

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    auth_svc = AuthService(secret_key="test-secret", public_key_pem=public_pem)
    payload = {
        "sub": "tantra-execution-worker",
        "aud": "masterdb",
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, private_pem, algorithm="RS256")

    with pytest.raises(AuthTokenError, match="Untrusted or missing token issuer"):
        auth_svc.decode_token(token)


def test_rs256_asymmetric_token_expired_rejected():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    from auth.service import AuthService, AuthTokenError

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    auth_svc = AuthService(secret_key="test-secret", public_key_pem=public_pem)
    payload = {
        "sub": "tantra-execution-worker",
        "iss": "tantra-sarathi",
        "aud": "masterdb",
        "exp": int(time.time()) - 60,
    }
    token = jwt.encode(payload, private_pem, algorithm="RS256")

    with pytest.raises(AuthTokenError, match="Token has expired"):
        auth_svc.decode_token(token)


def test_unsupported_algorithm_rejected():
    from auth.service import AuthService, AuthTokenError
    auth_svc = AuthService(secret_key="test-secret")
    # Fabricate a token with an unsupported alg header
    payload = {"sub": "attacker", "exp": int(time.time()) + 3600}
    token = jwt.encode(payload, "key", algorithm="HS512")
    with pytest.raises(AuthTokenError, match="Unsupported algorithm"):
        auth_svc.decode_token(token)

