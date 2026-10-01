"""
Tests for MASTERDB Capability Discovery API.
"""
from fastapi.testclient import TestClient
from main import app
from auth.service import AuthService

auth_service = AuthService()
client = TestClient(app)


def _get_token(actor="test-app", roles=None):
    res = client.post("/auth/token", json={"actor": actor, "roles": roles or ["ecosystem-reader"]})
    assert res.status_code == 200
    return res.json()["access_token"]


def test_list_capabilities_requires_auth():
    res = client.get("/capabilities")
    assert res.status_code == 401


def test_list_all_default_capabilities():
    token = _get_token()
    res = client.get("/capabilities", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 4
    capability_ids = [c["capability_id"] for c in data]
    assert "cap-mangrove-monitoring" in capability_ids
    assert "cap-maritime-cargo" in capability_ids
    assert "cap-fin-market-analytics" in capability_ids
    assert "cap-bharat-mala-highways" in capability_ids


def test_filter_capabilities_by_domain():
    token = _get_token()
    res = client.get("/capabilities?domain=geospatial", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["domain"] == "geospatial"
    assert data[0]["capability_id"] == "cap-mangrove-monitoring"


def test_search_capabilities():
    token = _get_token()
    res = client.get("/capabilities?search=maritime", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 1
    assert any("maritime" in c["capability_id"] for c in data)


def test_get_capability_by_id():
    token = _get_token()
    res = client.get("/capabilities/cap-mangrove-monitoring", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    cap = res.json()
    assert cap["capability_id"] == "cap-mangrove-monitoring"
    assert cap["domain"] == "geospatial"
    assert cap["dataset_id"] == "ds-mangrove-001"


def test_get_capability_not_found():
    token = _get_token()
    res = client.get("/capabilities/nonexistent-cap", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 404
