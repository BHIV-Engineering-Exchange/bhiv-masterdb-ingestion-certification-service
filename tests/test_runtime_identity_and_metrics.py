import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture(autouse=True)
def _fresh_services():
    main.bcaes_registry_service = main.BCAESRegistryService()
    main.canonical_repository_service = main.CanonicalRepositoryService()
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


def test_runtime_identity_is_public_no_auth_required(client):
    resp = client.get("/runtime/identity")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service_name"] == "MASTERDB"
    assert body["auth"]["token_endpoint"] == "/auth/token"
    assert body["health_check_url"] == "/health"


def test_runtime_identity_lists_all_current_api_groups(client):
    body = client.get("/runtime/identity").json()
    assert set(body["api_groups"].keys()) >= {
        "bcaes_registry", "canonical_repository", "auth", "runtime",
    }


def test_runtime_identity_is_honest_about_not_being_registered(client):
    body = client.get("/runtime/identity").json()
    assert body["status"] == "not_yet_registered"


def test_metrics_is_public_and_prometheus_formatted(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "masterdb_up 1" in resp.text
    assert "# TYPE masterdb_bcaes_registry_objects_total gauge" in resp.text


def test_metrics_reflects_actual_registered_object_counts(client):
    token, _ = main.auth_service.issue_token("Kavy", [])
    client.post(
        "/bcaes/registries/capability/objects",
        json={"name": "X", "purpose": "p", "owner": "Kavy", "authority_boundaries": ["Kavy"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = client.get("/metrics")
    assert 'masterdb_bcaes_registry_objects_total{registry_type="capability"} 1' in resp.text


def test_metrics_reflects_actual_document_count(client):
    token, _ = main.auth_service.issue_token("Kavy", ["bcaes-editor"])
    client.post(
        "/canonical-repository/documents",
        json={"category": "bcaes_vol_4", "title": "Vol 4", "owner": "Kavy"},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = client.get("/metrics")
    assert "masterdb_canonical_documents_total 1" in resp.text
