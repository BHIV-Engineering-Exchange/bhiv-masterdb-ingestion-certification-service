"""
Tests for Governed Capability Data Retrieval & Provenance.
"""
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def _get_token(actor="retrieval-tester", roles=None):
    res = client.post("/auth/token", json={"actor": actor, "roles": roles or ["ecosystem-reader"]})
    assert res.status_code == 200
    return res.json()["access_token"]


def test_retrieve_capability_data_success():
    token = _get_token(actor="DATA_CONSUMER", roles=["ecosystem-reader"])
    
    # 1. Request access
    req_res = client.post(
        "/access/request",
        json={
            "application_id": "DATA_CONSUMER",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert req_res.status_code == 200
    grant = req_res.json()

    # 2. Retrieve data using access_token grant
    ret_res = client.post(
        "/capabilities/cap-mangrove-monitoring/retrieve",
        json={
            "application_id": "DATA_CONSUMER",
            "access_token": grant["access_token"],
            "query_params": {"region": "Sundarbans-North"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ret_res.status_code == 200
    data = ret_res.json()
    assert "data" in data
    assert data["capability"]["capability_id"] == "cap-mangrove-monitoring"
    assert data["capability"]["domain"] == "geospatial"
    assert "provenance" in data
    assert "request_id" in data
    assert data["data"]["region"] == "Sundarbans-North"

    # 3. Verify audit record
    req_id = grant["request_id"]
    audit_res = client.get(f"/access/{req_id}", headers={"Authorization": f"Bearer {token}"})
    assert audit_res.status_code == 200
    audit_contract = audit_res.json()
    assert audit_contract["request_id"] == req_id
    assert audit_contract["authorized"] is True


def test_access_grant_cannot_be_reused_for_another_capability_or_application():
    token = _get_token(actor="DATA_CONSUMER", roles=["ecosystem-reader"])
    headers = {"Authorization": f"Bearer {token}"}
    grant_response = client.post(
        "/access/request",
        json={
            "application_id": "DATA_CONSUMER",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers=headers,
    )
    assert grant_response.status_code == 200
    grant = grant_response.json()

    wrong_capability = client.post(
        "/capabilities/cap-maritime-cargo/retrieve",
        json={"application_id": "DATA_CONSUMER", "access_token": grant["access_token"]},
        headers=headers,
    )
    assert wrong_capability.status_code == 403

    wrong_application = client.post(
        "/capabilities/cap-mangrove-monitoring/retrieve",
        json={"application_id": "OTHER_APPLICATION", "access_token": grant["access_token"]},
        headers=headers,
    )
    assert wrong_application.status_code == 403


def test_access_grant_cannot_be_reused_by_another_authenticated_actor():
    owner_token = _get_token(actor="grant-owner", roles=["ecosystem-reader"])
    other_actor_token = _get_token(actor="other-actor", roles=["ecosystem-reader"])
    grant_response = client.post(
        "/access/request",
        json={
            "application_id": "SHARED_CONSUMER_APP",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert grant_response.status_code == 200
    grant = grant_response.json()

    for credential in (
        {"access_token": grant["access_token"]},
        {"request_id": grant["request_id"]},
    ):
        response = client.post(
            "/capabilities/cap-mangrove-monitoring/retrieve",
            json={"application_id": "SHARED_CONSUMER_APP", **credential},
            headers={"Authorization": f"Bearer {other_actor_token}"},
        )
        assert response.status_code == 403
