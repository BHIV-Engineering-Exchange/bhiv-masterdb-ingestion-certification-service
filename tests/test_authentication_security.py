from fastapi.testclient import TestClient
import pytest
import main
from auth.service import AuthService, AuthTokenError


@pytest.fixture
def client():
    return TestClient(main.app)


def test_public_token_endpoint_ignores_self_assigned_roles(client):
    # Attempt privilege escalation by passing bhiv-admin
    resp = client.post("/auth/token", json={"actor": "normal-user", "roles": ["bhiv-admin"]})
    assert resp.status_code == 200
    data = resp.json()
    assert "bhiv-admin" not in data["roles"]
    assert data["roles"] == ["viewer", "dashboard-viewer"]

    # Verify decoded token identity
    identity = main.auth_service.decode_token(data["access_token"])
    assert identity.actor == "normal-user"
    assert "bhiv-admin" not in identity.roles


def test_public_token_endpoint_assigns_trusted_roles_for_configured_admin(client):
    resp = client.post("/auth/token", json={"actor": "kavy", "roles": ["viewer"]})
    assert resp.status_code == 200
    data = resp.json()
    assert "bhiv-admin" in data["roles"]


def test_public_token_endpoint_invalid_credentials_returns_401(client, monkeypatch):
    monkeypatch.setenv("AUTH_PASSWORD", "secret123")
    resp = client.post("/auth/token", json={"actor": "kavy", "password": "wrongpassword"})
    assert resp.status_code == 401
    assert "Invalid credentials" in resp.json()["error"]["message"]


def test_public_token_endpoint_valid_credentials_returns_200(client, monkeypatch):
    monkeypatch.setenv("AUTH_PASSWORD", "secret123")
    resp = client.post("/auth/token", json={"actor": "kavy", "password": "secret123"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_protected_endpoint_without_token_returns_401(client):
    resp = client.get("/databases")
    assert resp.status_code == 401


def test_protected_endpoint_invalid_token_returns_401(client):
    resp = client.get("/databases", headers={"Authorization": "Bearer invalid.jwt.token"})
    assert resp.status_code == 401
