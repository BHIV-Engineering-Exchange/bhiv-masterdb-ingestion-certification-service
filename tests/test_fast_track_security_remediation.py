"""
Tests for MasterDB Fast-Track Security Remediation:
- F-02: Production RS256 key validation (missing, malformed, <2048-bit, valid, no HS256 fallback)
- F-03: Removal of implicit sibling-key discovery (no directory walking, explicit path/PEM only)
- F-06: Require standard JWT subject (sub required, non-empty string, no actor/trace_id fallbacks)
"""
import time
import pytest
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from auth.service import AuthService, AuthTokenError, validate_rsa_public_key


@pytest.fixture
def rsa_2048_pair():
    """Generates a valid 2048-bit RSA key pair for testing."""
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
def rsa_1024_pair():
    """Generates an insufficiently strong 1024-bit RSA key pair for testing."""
    priv = rsa.generate_private_key(public_exponent=65537, key_size=1024)
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


# =============================================================================
# F-02: PRODUCTION RS256 PUBLIC-KEY VALIDATION
# =============================================================================

def test_f02_missing_public_key_fails_startup_in_production(monkeypatch):
    """Production startup must fail closed if no authoritative RS256 public key is provided."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_JWT_SECRET", "stable-prod-secret-at-least-32-chars-long!")
    monkeypatch.delenv("AUTH_JWT_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("AUTH_JWT_PUBLIC_KEY_PATH", raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        AuthService()
    assert "AUTH_JWT_PUBLIC_KEY or AUTH_JWT_PUBLIC_KEY_PATH must be configured in production mode" in str(exc_info.value)


def test_f02_malformed_pem_fails_startup_in_production(monkeypatch):
    """Production startup must fail closed if the RS256 public key is a corrupted or malformed PEM."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_JWT_SECRET", "stable-prod-secret-at-least-32-chars-long!")
    monkeypatch.setenv("AUTH_JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\ncorrupted-garbage\n-----END PUBLIC KEY-----")

    with pytest.raises(RuntimeError) as exc_info:
        AuthService()
    assert "Authoritative RS256 public key is malformed or invalid" in str(exc_info.value)


def test_f02_insufficient_key_size_fails_startup_in_production(rsa_1024_pair, monkeypatch):
    """Production startup must fail closed if the RSA key size is < 2048 bits (e.g. 1024 bits)."""
    _, pub_1024_pem = rsa_1024_pair
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_JWT_SECRET", "stable-prod-secret-at-least-32-chars-long!")
    monkeypatch.setenv("AUTH_JWT_PUBLIC_KEY", pub_1024_pem)

    with pytest.raises(RuntimeError) as exc_info:
        AuthService()
    msg = str(exc_info.value).lower()
    assert "insufficient" in msg
    assert "2048" in msg


def test_f02_valid_2048_bit_key_starts_up_in_production(rsa_2048_pair, monkeypatch):
    """Production startup must succeed when configured with an authoritative 2048-bit RSA public key."""
    _, pub_2048_pem = rsa_2048_pair
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_JWT_SECRET", "stable-prod-secret-at-least-32-chars-long!")
    monkeypatch.setenv("AUTH_JWT_PUBLIC_KEY", pub_2048_pem)

    service = AuthService()
    assert service.is_production is True
    assert service.public_key_pem == pub_2048_pem.strip()


def test_f02_no_fallback_to_hs256_in_production(rsa_2048_pair, monkeypatch):
    """In production mode, HS256 tokens must be strictly rejected even if AUTH_JWT_SECRET is configured."""
    _, pub_2048_pem = rsa_2048_pair
    secret = "stable-prod-secret-at-least-32-chars-long!"
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_JWT_SECRET", secret)
    monkeypatch.setenv("AUTH_JWT_PUBLIC_KEY", pub_2048_pem)

    service = AuthService()
    hs_token = jwt.encode(
        {"sub": "operator", "roles": ["viewer"], "exp": int(time.time()) + 3600},
        secret,
        algorithm="HS256",
    )
    with pytest.raises(AuthTokenError, match="HS256 symmetric tokens are rejected in production mode"):
        service.decode_token(hs_token)


# =============================================================================
# F-03: REMOVE IMPLICIT SIBLING-KEY DISCOVERY
# =============================================================================

def test_f03_sibling_directory_never_consulted_when_key_unconfigured(monkeypatch):
    """When public key environment variables are unset, sibling directories are NEVER consulted."""
    monkeypatch.delenv("AUTH_JWT_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("AUTH_JWT_PUBLIC_KEY_PATH", raising=False)

    service = AuthService(secret_key="dev-secret")
    assert service.public_key_pem is None


def test_f03_configured_public_key_path_used_directly(rsa_2048_pair, monkeypatch, tmp_path):
    """Explicitly configured AUTH_JWT_PUBLIC_KEY_PATH is read and respected."""
    _, pub_2048_pem = rsa_2048_pair
    key_file = tmp_path / "authoritative_pubkey.pem"
    key_file.write_text(pub_2048_pem, encoding="utf-8")

    monkeypatch.delenv("AUTH_JWT_PUBLIC_KEY", raising=False)
    monkeypatch.setenv("AUTH_JWT_PUBLIC_KEY_PATH", str(key_file))

    service = AuthService(secret_key="dev-secret")
    assert service.public_key_pem == pub_2048_pem.strip()


def test_f03_nonexistent_key_path_does_not_fall_back_to_sibling(monkeypatch, tmp_path):
    """If AUTH_JWT_PUBLIC_KEY_PATH points to a non-existent file, it does NOT fall back to sibling directories."""
    missing_file = tmp_path / "does_not_exist.pem"
    monkeypatch.delenv("AUTH_JWT_PUBLIC_KEY", raising=False)
    monkeypatch.setenv("AUTH_JWT_PUBLIC_KEY_PATH", str(missing_file))

    service = AuthService(secret_key="dev-secret")
    assert service.public_key_pem is None


# =============================================================================
# F-06: REQUIRE STANDARD JWT SUBJECT (NO ACTOR / TRACE_ID FALLBACKS)
# =============================================================================

def test_f06_valid_sub_accepted(rsa_2048_pair):
    """Token with a valid, non-empty string 'sub' claim is accepted."""
    priv_pem, pub_pem = rsa_2048_pair
    service = AuthService(public_key_pem=pub_pem)

    payload = {
        "sub": "operator-principal-123",
        "iss": "tantra-sarathi",
        "aud": "masterdb",
        "roles": ["operator", "viewer"],
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }
    token = jwt.encode(payload, priv_pem, algorithm="RS256")
    identity = service.decode_token(token)
    assert identity.actor == "operator-principal-123"
    assert "operator" in identity.roles


def test_f06_missing_sub_rejected(rsa_2048_pair):
    """Token missing the 'sub' claim is rejected even if exp, iss, aud, and roles are valid."""
    priv_pem, pub_pem = rsa_2048_pair
    service = AuthService(public_key_pem=pub_pem)

    payload = {
        "iss": "tantra-sarathi",
        "aud": "masterdb",
        "roles": ["operator"],
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }
    token = jwt.encode(payload, priv_pem, algorithm="RS256")
    with pytest.raises(AuthTokenError, match="missing a subject"):
        service.decode_token(token)


def test_f06_actor_claim_cannot_substitute_for_sub(rsa_2048_pair):
    """A caller-supplied 'actor' claim CANNOT substitute for missing 'sub'."""
    priv_pem, pub_pem = rsa_2048_pair
    service = AuthService(public_key_pem=pub_pem)

    payload = {
        "actor": "claimed-actor",
        "iss": "tantra-sarathi",
        "aud": "masterdb",
        "roles": ["operator"],
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }
    token = jwt.encode(payload, priv_pem, algorithm="RS256")
    with pytest.raises(AuthTokenError, match="missing a subject"):
        service.decode_token(token)


def test_f06_trace_id_cannot_substitute_for_sub(rsa_2048_pair):
    """A telemetry 'trace_id' header/claim CANNOT substitute for user principal 'sub'."""
    priv_pem, pub_pem = rsa_2048_pair
    service = AuthService(public_key_pem=pub_pem)

    payload = {
        "trace_id": "telemetry-trace-uuid-9999",
        "actor": "claimed-actor",
        "iss": "tantra-sarathi",
        "aud": "masterdb",
        "roles": ["operator"],
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }
    token = jwt.encode(payload, priv_pem, algorithm="RS256")
    with pytest.raises(AuthTokenError, match="missing a subject"):
        service.decode_token(token)


def test_f06_empty_or_whitespace_sub_rejected(rsa_2048_pair):
    """Token with an empty or whitespace-only 'sub' claim is rejected."""
    priv_pem, pub_pem = rsa_2048_pair
    service = AuthService(public_key_pem=pub_pem)

    for empty_val in ["", "   ", "\t\n"]:
        payload = {
            "sub": empty_val,
            "iss": "tantra-sarathi",
            "aud": "masterdb",
            "roles": ["operator"],
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        token = jwt.encode(payload, priv_pem, algorithm="RS256")
        with pytest.raises(AuthTokenError):
            service.decode_token(token)


def test_f06_non_string_sub_rejected(rsa_2048_pair):
    """Token with a non-string 'sub' claim (e.g. integer, list) is rejected."""
    priv_pem, pub_pem = rsa_2048_pair
    service = AuthService(public_key_pem=pub_pem)

    for bad_val in [12345, True, ["not-a-string"], {"key": "val"}]:
        payload = {
            "sub": bad_val,
            "iss": "tantra-sarathi",
            "aud": "masterdb",
            "roles": ["operator"],
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        token = jwt.encode(payload, priv_pem, algorithm="RS256")
        with pytest.raises(AuthTokenError):
            service.decode_token(token)
