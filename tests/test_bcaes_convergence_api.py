import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture(autouse=True)
def _fresh_registry():
    main.bcaes_registry_service = main.BCAESRegistryService()
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


def _register_product(client, name="MASTERDB"):
    token, _ = main.auth_service.issue_token("Kavy", [])
    resp = client.post(
        "/bcaes/registries/product/objects",
        json={
            "name": name,
            "purpose": "p",
            "owner": "Kavy",
            "authority_boundaries": ["Kavy"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_convergence_requires_registered_object(client):
    resp = client.post("/bcaes/convergence/prd-nonexistent", json={})
    assert resp.status_code == 404


def test_convergence_upsert_and_get(client):
    product = _register_product(client)
    resp = client.post(
        f"/bcaes/convergence/{product['id']}",
        json={
            "integration_status": "complete",
            "sdk_adoption": "in_progress",
            "remaining_work": ["wire replay to TANTRA"],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["integration_status"] == "complete"
    assert body["sdk_adoption"] == "in_progress"
    assert body["remaining_work"] == ["wire replay to TANTRA"]

    fetched = client.get(f"/bcaes/convergence/{product['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["maturity_score"] == pytest.approx(1 / 7, rel=1e-3)


def test_convergence_get_missing_returns_404(client):
    product = _register_product(client)
    resp = client.get(f"/bcaes/convergence/{product['id']}")
    assert resp.status_code == 404


def test_convergence_list(client):
    p1 = _register_product(client, "MASTERDB")
    p2 = _register_product(client, "TANTRA")
    client.post(f"/bcaes/convergence/{p1['id']}", json={"integration_status": "complete"})
    client.post(f"/bcaes/convergence/{p2['id']}", json={"integration_status": "not_started"})
    resp = client.get("/bcaes/convergence")
    assert resp.status_code == 200
    assert resp.json()["count"] == 2


def test_convergence_upsert_is_a_merge_patch_across_calls(client):
    """Two different collaborators updating two different dimensions in
    separate calls must not stomp on each other's declared status."""
    product = _register_product(client)
    client.post(f"/bcaes/convergence/{product['id']}", json={"integration_status": "complete"})
    resp = client.post(f"/bcaes/convergence/{product['id']}", json={"sdk_adoption": "complete"})
    body = resp.json()
    assert body["sdk_adoption"] == "complete"
    assert body["integration_status"] == "complete"


def test_snapshot_is_generated_dynamically(client):
    product = _register_product(client)
    client.post(
        f"/bcaes/convergence/{product['id']}",
        json={"integration_status": "complete", "production_readiness": "complete"},
    )
    resp = client.get("/bcaes/snapshot")
    assert resp.status_code == 200
    body = resp.json()
    assert body["registries"]["product"] == 1
    assert body["total_objects"] == 1
    assert body["convergence"]["objects_with_convergence_data"] == 1
    assert body["convergence"]["production_ready_count"] == 1
    assert body["architecture_validation"]["passed"] is True
    assert "generated_at" in body


def test_snapshot_tracks_untracked_objects(client):
    product = _register_product(client)
    resp = client.get("/bcaes/snapshot")
    body = resp.json()
    assert product["id"] in body["convergence"]["untracked_object_ids"]
    assert body["convergence"]["objects_without_convergence_data"] == 1
