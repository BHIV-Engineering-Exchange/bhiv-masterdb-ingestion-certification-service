import uuid

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _token(actor, roles):
    response = client.post(
        "/auth/token",
        json={"actor": actor, "roles": roles, "password": "test-admin-password"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _capability(capability_id, version):
    return {
        "capability_id": capability_id,
        "capability_name": "Versioned Test Capability",
        "description": "Capability API registration and version history test.",
        "dataset_id": f"ds-{capability_id}",
        "capability_version": version,
        "contract_version": "1.0.0",
        "domain": "test",
        "schema_version": "v1",
        "status": "EXPERIMENTAL",
        "supported_access_methods": ["QUERY", "REFERENCE"],
        "required_purpose": "testing",
        "authorization_requirements": {
            "required_roles": ["ecosystem-reader"],
            "allowed_consumers": ["test-app"],
        },
        "provenance": {"source": "test fixture"},
    }


def test_capability_registration_search_and_immutable_versions(monkeypatch):
    monkeypatch.setenv("AUTH_PASSWORD", "test-admin-password")
    admin_token = _token("admin", ["bhiv-admin"])
    headers = {"Authorization": f"Bearer {admin_token}"}
    capability_id = f"cap-registration-{uuid.uuid4().hex[:10]}"

    denied = client.post(
        "/capabilities/register",
        json=_capability(capability_id, "1.0.0"),
        headers={"Authorization": f"Bearer {_token('viewer', ['ecosystem-reader'])}"},
    )
    assert denied.status_code == 403

    first = client.post(
        "/capabilities/register",
        json=_capability(capability_id, "1.0.0"),
        headers=headers,
    )
    assert first.status_code == 201

    second = client.post(
        "/capabilities/register",
        json=_capability(capability_id, "2.0.0"),
        headers=headers,
    )
    assert second.status_code == 201

    versions = client.get(f"/capabilities/{capability_id}/versions", headers=headers)
    assert versions.status_code == 200
    assert [version["capability_version"] for version in versions.json()] == ["1.0.0", "2.0.0"]

    search = client.get(f"/capabilities?search={capability_id}", headers=headers)
    assert search.status_code == 200
    assert any(item["capability_id"] == capability_id for item in search.json())

    duplicate = client.post(
        "/capabilities/register",
        json=_capability(capability_id, "2.0.0"),
        headers=headers,
    )
    assert duplicate.status_code == 409
