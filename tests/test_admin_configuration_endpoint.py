from fastapi.testclient import TestClient

import main


def test_configuration_requires_token():
    client = TestClient(main.app)
    resp = client.get("/admin/configuration")
    assert resp.status_code == 401


def test_configuration_requires_admin_role():
    client = TestClient(main.app)
    token, _ = main.auth_service.issue_token("Kavy", [])
    resp = client.get("/admin/configuration", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_configuration_report_returns_expected_keys():
    client = TestClient(main.app)
    token, _ = main.auth_service.issue_token("Kavy", ["bhiv-admin"])
    resp = client.get("/admin/configuration", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert "AUTH_JWT_SECRET" in body
    assert "MASTERDB_DATABASE_URL" in body


def test_configuration_report_never_leaks_secret_values(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", "should-never-appear-in-response")
    client = TestClient(main.app)
    token, _ = main.auth_service.issue_token("Kavy", ["bhiv-admin"])
    resp = client.get("/admin/configuration", headers={"Authorization": f"Bearer {token}"})
    assert "should-never-appear-in-response" not in resp.text
