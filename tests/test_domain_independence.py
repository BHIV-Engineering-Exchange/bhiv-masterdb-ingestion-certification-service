"""
Tests for Domain Independence — Proving the integration contract does NOT change across domains.
"""
from fastapi.testclient import TestClient
import main
from models import Capability, CapabilityStatus

client = TestClient(main.app)


def _get_token(actor="domain-tester"):
    res = client.post("/auth/token", json={"actor": actor, "roles": ["ecosystem-reader"]})
    assert res.status_code == 200
    return res.json()["access_token"]


def test_domain_independence_across_varied_domains():
    token = _get_token()

    # Register capabilities in non-geospatial domains
    custom_caps = [
        Capability(
            capability_id="cap-edu-learning-analytics",
            capability_name="Universal Education Progress Dataset",
            description="Student learning outcomes and curriculum progress metrics",
            dataset_id="ds-edu-001",
            domain="education",
            required_purpose="learning_analytics",
        ),
        Capability(
            capability_id="cap-robotics-telemetry",
            capability_name="Autonomous Robot Fleet Telemetry",
            description="Robotic sensor logs, kinematic profiles, and obstacle navigation telemetry",
            dataset_id="ds-robotics-001",
            domain="robotics",
            required_purpose="autonomous_navigation",
        ),
        Capability(
            capability_id="cap-xr-spatial-mapping",
            capability_name="Spatial Computing & XR Mesh Registry",
            description="3D environment spatial mesh and anchor registration data",
            dataset_id="ds-xr-001",
            domain="xr",
            required_purpose="spatial_rendering",
        ),
    ]

    for cap in custom_caps:
        main.capability_registry_service.register_capability(cap)

    # Verify discovery, contract, access request, and data retrieval for ALL domains
    for cap in custom_caps:
        # 1. Discover
        disc_res = client.get(f"/capabilities/{cap.capability_id}", headers={"Authorization": f"Bearer {token}"})
        assert disc_res.status_code == 200

        # 2. Contract
        contract_res = client.get(f"/capabilities/{cap.capability_id}/contract", headers={"Authorization": f"Bearer {token}"})
        assert contract_res.status_code == 200
        contract = contract_res.json()
        assert contract["domain"] == cap.domain

        # 3. Access Request
        access_res = client.post(
            "/access/request",
            json={
                "application_id": f"APP-{cap.domain.upper()}",
                "capability_id": cap.capability_id,
                "purpose": cap.required_purpose,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert access_res.status_code == 200
        grant = access_res.json()
        assert grant["authorized"] is True

        # 4. Data Retrieval
        ret_res = client.post(
            f"/capabilities/{cap.capability_id}/retrieve",
            json={
                "application_id": f"APP-{cap.domain.upper()}",
                "access_token": grant["access_token"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert ret_res.status_code == 200
        ret_body = ret_res.json()
        assert ret_body["capability"]["domain"] == cap.domain
        assert "data" in ret_body
        assert "provenance" in ret_body
