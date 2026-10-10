"""
Tests for MASTERDB Capability Access Authorization & Policy Evaluation.
"""
import uuid

from fastapi.testclient import TestClient
import main

client = TestClient(main.app)


def _get_token(actor="auth-tester", roles=None):
    res = client.post("/auth/token", json={"actor": actor, "roles": roles or ["ecosystem-reader"]})
    assert res.status_code == 200
    return res.json()["access_token"]


def test_request_access_success():
    token = _get_token(actor="VALID_CONSUMER", roles=["ecosystem-reader"])
    payload = {
        "application_id": "VALID_CONSUMER",
        "capability_id": "cap-mangrove-monitoring",
        "purpose": "environmental_monitoring",
    }
    res = client.post("/access/request", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    grant = res.json()
    assert grant["authorized"] is True
    assert grant["application_id"] == "VALID_CONSUMER"
    assert grant["capability_id"] == "cap-mangrove-monitoring"
    assert "access_token" in grant
    assert grant["access_token"].startswith("grant-")


def test_request_access_unauthorized_consumer():
    token = _get_token(actor="auth-tester")
    from models import Capability

    capability_id = f"cap-restricted-{uuid.uuid4().hex[:10]}"
    main.capability_registry_service.register_capability(
        Capability(
            capability_id=capability_id,
            capability_name="Classified Defense Dataset",
            description="Restricted classified intelligence capability",
            dataset_id="ds-defense-001",
            authorization_requirements={
                "required_roles": ["super-secret-admin"],
                "allowed_consumers": ["SPECIAL_DEFENSE_APP"],
            },
        )
    )

    payload = {
        "application_id": "UNAUTHORIZED_CONSUMER_APP",
        "capability_id": capability_id,
        "purpose": "unauthorized_access",
    }
    res = client.post("/access/request", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403
    body = res.json()
    assert "error" in body


def test_request_access_nonexistent_capability():
    token = _get_token()
    payload = {
        "application_id": "APP1",
        "capability_id": "invalid-cap-999",
        "purpose": "general_reuse",
    }
    res = client.post("/access/request", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 404


def test_request_access_rejects_unapproved_purpose():
    token = _get_token(actor="VALID_CONSUMER", roles=["ecosystem-reader"])
    payload = {
        "application_id": "VALID_CONSUMER",
        "capability_id": "cap-mangrove-monitoring",
        "purpose": "unrelated_financial_analysis",
    }
    res = client.post("/access/request", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403


def test_request_access_rejects_unregistered_capability_version():
    token = _get_token(actor="VALID_CONSUMER", roles=["ecosystem-reader"])
    payload = {
        "application_id": "VALID_CONSUMER",
        "capability_id": "cap-mangrove-monitoring",
        "capability_version": "9.9.9",
        "purpose": "environmental_monitoring",
    }
    res = client.post("/access/request", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403
