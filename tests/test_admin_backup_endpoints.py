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


def _admin_headers():
    token, _ = main.auth_service.issue_token("Kavy", ["bhiv-admin"])
    return {"Authorization": f"Bearer {token}"}


def test_backup_requires_token(client):
    resp = client.get("/admin/backup")
    assert resp.status_code == 401


def test_backup_requires_admin_role(client):
    token, _ = main.auth_service.issue_token("Kavy", [])
    resp = client.get("/admin/backup", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_backup_of_in_memory_services_is_empty_but_valid(client):
    resp = client.get("/admin/backup", headers=_admin_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["stores"]["bcaes_registry"]["persisted"] is False
    assert body["stores"]["canonical_repository"]["persisted"] is False


def test_restore_requires_admin_role(client):
    token, _ = main.auth_service.issue_token("Kavy", [])
    resp = client.post(
        "/admin/restore", json={"stores": {}}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


def test_restore_into_unconfigured_in_memory_service_returns_400(client):
    snapshot = {"stores": {"bcaes_registry": {"persisted": True, "records": [{"id": "x", "name": "y"}]}}}
    resp = client.post("/admin/restore", json=snapshot, headers=_admin_headers())
    assert resp.status_code == 400


def test_restore_of_empty_snapshot_into_in_memory_service_succeeds(client):
    snapshot = {
        "stores": {
            "bcaes_registry": {"persisted": False, "records": []},
            "canonical_repository": {"persisted": False, "records": []},
        }
    }
    resp = client.post("/admin/restore", json=snapshot, headers=_admin_headers())
    assert resp.status_code == 200
    assert resp.json()["restored"] == {"bcaes_registry": 0, "canonical_repository": 0}


def test_restore_is_immediately_readable_on_the_same_running_service(client, tmp_path):
    """Regression test: restore_snapshot() writes directly to the
    persistent store, bypassing the service's in-memory cache. An earlier
    version of this endpoint left that cache stale, so a GET immediately
    after a 'successful' restore 404'd. This must not happen — restore
    must be visible without restarting the process."""
    from services.sql_artifact_store import SqlArtifactStore

    db_url = f"sqlite:///{tmp_path}/demo.db"
    main.bcaes_registry_service = main.BCAESRegistryService(
        artifact_store=SqlArtifactStore(db_url, store_name="bcaes_registry")
    )

    register_resp = client.post(
        "/bcaes/registries/product/objects",
        json={"name": "MASTERDB", "purpose": "p", "owner": "Kavy", "authority_boundaries": ["Kavy"]},
        headers=_admin_headers(),
    )
    object_id = register_resp.json()["id"]

    backup = client.get("/admin/backup", headers=_admin_headers()).json()

    # Simulate a restart: fresh service instance, fresh empty database.
    main.bcaes_registry_service = main.BCAESRegistryService(
        artifact_store=SqlArtifactStore(f"sqlite:///{tmp_path}/fresh.db", store_name="bcaes_registry")
    )
    restore_resp = client.post("/admin/restore", json=backup, headers=_admin_headers())
    assert restore_resp.status_code == 200
    assert restore_resp.json()["restored"]["bcaes_registry"] == 1

    # The critical check: read it back on the SAME client/service instance,
    # with no reconstruction in between — this is exactly what a real
    # POST /admin/restore caller does next.
    verify_resp = client.get(f"/bcaes/registries/product/objects/{object_id}")
    assert verify_resp.status_code == 200
    assert verify_resp.json()["name"] == "MASTERDB"
