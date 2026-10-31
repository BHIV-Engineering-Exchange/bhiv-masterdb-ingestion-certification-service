"""
Tests for Governed Capability Data Retrieval & Provenance.
"""
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def _get_token(actor="retrieval-tester", roles=None):
    res = client.post("/auth/token", json={"actor": actor, "password": "test-auth-password", "roles": roles or ["ecosystem-reader"]})
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


def test_revoked_access_grant_denies_retrieval():
    token = _get_token(actor="DATA_CONSUMER", roles=["ecosystem-reader"])
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

    # Revoke grant via DELETE /access/{request_id}
    del_res = client.delete(f"/access/{grant['request_id']}", headers={"Authorization": f"Bearer {token}"})
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "revoked"

    # Attempt retrieval with revoked token -> must be rejected with 403
    ret_res = client.post(
        "/capabilities/cap-mangrove-monitoring/retrieve",
        json={
            "application_id": "DATA_CONSUMER",
            "access_token": grant["access_token"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ret_res.status_code == 403
    assert "revoked" in ret_res.text.lower()


def test_retrieval_trace_and_execution_correlation():
    token = _get_token(actor="DATA_CONSUMER", roles=["ecosystem-reader"])
    req_res = client.post(
        "/access/request",
        json={
            "application_id": "DATA_CONSUMER",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    grant = req_res.json()

    test_trace_id = "trace-tantra-cross-service-001"
    test_exec_id = "exec-tantra-cross-service-001"

    ret_res = client.post(
        "/capabilities/cap-mangrove-monitoring/retrieve",
        json={
            "application_id": "DATA_CONSUMER",
            "access_token": grant["access_token"],
            "trace_id": test_trace_id,
            "execution_id": test_exec_id,
            "query_params": {"region": "Sundarbans-North"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ret_res.status_code == 200
    payload = ret_res.json()
    assert payload["trace_id"] == test_trace_id
    assert payload["execution_id"] == test_exec_id
    assert "content_digest_sha256" in payload["provenance"]


def test_expired_access_grant_denies_retrieval():
    token = _get_token(actor="DATA_CONSUMER", roles=["ecosystem-reader"])
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

    from main import capability_registry_service
    contract = capability_registry_service.get_access_contract(grant["access_token"])
    contract.expires_at = "2020-01-01T00:00:00+00:00"

    ret_res = client.post(
        "/capabilities/cap-mangrove-monitoring/retrieve",
        json={
            "application_id": "DATA_CONSUMER",
            "access_token": grant["access_token"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ret_res.status_code == 403
    assert "expired" in ret_res.text.lower()


def test_repeated_revoke_behavior():
    token = _get_token(actor="DATA_CONSUMER", roles=["ecosystem-reader"])
    req_res = client.post(
        "/access/request",
        json={
            "application_id": "DATA_CONSUMER",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    grant = req_res.json()

    # First revocation succeeds
    del1 = client.delete(f"/access/{grant['request_id']}", headers={"Authorization": f"Bearer {token}"})
    assert del1.status_code == 200

    # Second revocation returns 404 (grant not found or already revoked)
    del2 = client.delete(f"/access/{grant['request_id']}", headers={"Authorization": f"Bearer {token}"})
    assert del2.status_code == 404


def test_unauthorized_actor_cannot_revoke_grant():
    owner_token = _get_token(actor="DATA_CONSUMER", roles=["ecosystem-reader"])
    req_res = client.post(
        "/access/request",
        json={
            "application_id": "DATA_CONSUMER",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert req_res.status_code == 200
    grant = req_res.json()

    # Another non-admin actor attempts to revoke
    attacker_token = _get_token(actor="ATTACKER_CONSUMER", roles=["ecosystem-reader"])
    del_res = client.delete(f"/access/{grant['request_id']}", headers={"Authorization": f"Bearer {attacker_token}"})
    assert del_res.status_code == 403
    assert "Only bhiv-admin or the grant owner" in del_res.json()["error"]["message"]


def test_access_contract_audit_redacts_token_and_enforces_auth():
    owner_token = _get_token(actor="DATA_CONSUMER", roles=["ecosystem-reader"])
    req_res = client.post(
        "/access/request",
        json={
            "application_id": "DATA_CONSUMER",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert req_res.status_code == 200
    grant = req_res.json()
    req_id = grant["request_id"]

    # 1. Owner can audit contract -> access_token must be redacted
    audit_res = client.get(f"/access/{req_id}", headers={"Authorization": f"Bearer {owner_token}"})
    assert audit_res.status_code == 200
    audit_contract = audit_res.json()
    assert audit_contract["request_id"] == req_id
    assert audit_contract["access_token"] == "[REDACTED]"

    # 2. Unauthorized actor gets 403 Forbidden
    attacker_token = _get_token(actor="ATTACKER_CONSUMER", roles=["ecosystem-reader"])
    unauth_res = client.get(f"/access/{req_id}", headers={"Authorization": f"Bearer {attacker_token}"})
    assert unauth_res.status_code == 403
    assert "Only bhiv-admin or the grant owner" in unauth_res.json()["error"]["message"]


def test_revocation_persistence_failure_fails_closed(monkeypatch):
    owner_token = _get_token(actor="DATA_CONSUMER", roles=["ecosystem-reader"])
    req_res = client.post(
        "/access/request",
        json={
            "application_id": "DATA_CONSUMER",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert req_res.status_code == 200
    grant = req_res.json()
    req_id = grant["request_id"]

    from main import capability_registry_service

    # Simulate grant store failure during revocation
    def failing_save(*args, **kwargs):
        raise IOError("Disk quota exceeded or database connection dropped")

    if capability_registry_service.grant_store:
        monkeypatch.setattr(capability_registry_service.grant_store, "save", failing_save)

    del_res = client.delete(f"/access/{req_id}", headers={"Authorization": f"Bearer {owner_token}"})
    assert del_res.status_code == 500
    assert "Failed to persist access contract revocation" in del_res.json()["error"]["message"]
