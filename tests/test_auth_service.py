import time

import pytest

from auth.service import AuthService, AuthTokenError


def test_issue_and_decode_round_trip():
    service = AuthService(secret_key="test-secret")
    token, expires_at = service.issue_token("Kavy", ["bcaes-editor"])
    identity = service.decode_token(token)
    assert identity.actor == "Kavy"
    assert identity.roles == ["bcaes-editor"]
    assert expires_at


def test_decode_rejects_tampered_token():
    service = AuthService(secret_key="test-secret")
    token, _ = service.issue_token("Kavy", ["bcaes-editor"])
    # Corrupt a run of characters in the signature segment, not just the
    # last one — a single base64url char can sit on a padding bit that
    # doesn't change the decoded signature bytes, which made this flaky.
    tampered = token[:-12] + ("0123456789ab" if token[-12:] != "0123456789ab" else "ba9876543210")
    with pytest.raises(AuthTokenError):
        service.decode_token(tampered)


def test_decode_rejects_token_signed_with_different_secret():
    service_a = AuthService(secret_key="secret-a")
    service_b = AuthService(secret_key="secret-b")
    token, _ = service_a.issue_token("Kavy", ["bcaes-editor"])
    with pytest.raises(AuthTokenError):
        service_b.decode_token(token)


def test_decode_rejects_expired_token():
    service = AuthService(secret_key="test-secret", expiry_minutes=0)
    token, _ = service.issue_token("Kavy", ["bcaes-editor"])
    time.sleep(1.1)
    with pytest.raises(AuthTokenError):
        service.decode_token(token)


def test_no_secret_and_no_env_var_generates_a_working_random_secret(monkeypatch):
    monkeypatch.delenv("AUTH_JWT_SECRET", raising=False)
    service = AuthService()
    token, _ = service.issue_token("Kavy", [])
    identity = service.decode_token(token)
    assert identity.actor == "Kavy"


def test_env_var_secret_is_used_when_no_explicit_key(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", "from-env")
    issuer = AuthService()
    verifier = AuthService(secret_key="from-env")
    token, _ = issuer.issue_token("Kavy", [])
    identity = verifier.decode_token(token)
    assert identity.actor == "Kavy"
