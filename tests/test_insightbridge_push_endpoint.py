import httpx
import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


def test_push_requires_token(client):
    resp = client.post("/observability/push-to-insightbridge")
    assert resp.status_code == 401


def test_push_reports_not_configured_when_env_var_unset(client, monkeypatch):
    monkeypatch.delenv("PRAVAH_BHIV_INSIGHT_FLOW_BRIDGE", raising=False)
    token, _ = main.auth_service.issue_token("Kavy", [])
    resp = client.post(
        "/observability/push-to-insightbridge", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["pushed"] is False
    assert "not set" in body["reason"]


def test_push_succeeds_when_configured_and_reachable(client, monkeypatch):
    monkeypatch.setenv("PRAVAH_BHIV_INSIGHT_FLOW_BRIDGE", "https://example-insightbridge.test")

    def fake_post(url, json, timeout):
        return httpx.Response(200, json={"accepted": True}, request=httpx.Request("POST", url))

    monkeypatch.setattr("services.insightbridge_client.httpx.post", fake_post)
    token, _ = main.auth_service.issue_token("Kavy", [])
    resp = client.post(
        "/observability/push-to-insightbridge", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["pushed"] is True
    assert body["insightbridge_response"] == {"accepted": True}


def test_push_reports_failure_when_configured_but_unreachable(client, monkeypatch):
    monkeypatch.setenv("PRAVAH_BHIV_INSIGHT_FLOW_BRIDGE", "https://example-insightbridge.test")

    def fake_post(url, json, timeout):
        raise httpx.ConnectError("connection refused", request=httpx.Request("POST", url))

    monkeypatch.setattr("services.insightbridge_client.httpx.post", fake_post)
    token, _ = main.auth_service.issue_token("Kavy", [])
    resp = client.post(
        "/observability/push-to-insightbridge", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["pushed"] is False
