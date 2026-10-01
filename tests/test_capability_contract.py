"""
Tests for MASTERDB Machine-Readable Capability Contract API.
"""
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def _get_token(actor="contract-tester", roles=None):
    res = client.post("/auth/token", json={"actor": actor, "roles": roles or ["ecosystem-reader"]})
    assert res.status_code == 200
    return res.json()["access_token"]


def test_get_capability_contract_success():
    token = _get_token()
    res = client.get("/capabilities/cap-mangrove-monitoring/contract", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    contract = res.json()
    assert contract["capability_id"] == "cap-mangrove-monitoring"
    assert contract["contract_version"] == "1.0.0"
    assert contract["capability_version"] == "1.0.0"
    assert contract["domain"] == "geospatial"
    assert contract["dataset_id"] == "ds-mangrove-001"
    assert contract["required_purpose"] == "environmental_monitoring"
    assert "QUERY" in contract["supported_access_methods"]
    assert "access_endpoint" in contract
    assert "provenance_reference" in contract


def test_get_capability_contract_not_found():
    token = _get_token()
    res = client.get("/capabilities/cap-unknown/contract", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 404
