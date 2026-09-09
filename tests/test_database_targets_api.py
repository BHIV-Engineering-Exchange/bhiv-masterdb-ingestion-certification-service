from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path) -> TestClient:
    # Fresh, isolated stores per test so certification/ingestion records
    # from other test modules never leak in.
    main.artifact_store.reports_dir = tmp_path / "reports"
    main.artifact_store.reports_dir.mkdir(parents=True, exist_ok=True)
    main.database_router_service = main.DatabaseRouterService(
        certification_artifact_store=main.artifact_store,
        store_dir=str(tmp_path / "ingestion_jobs"),
    )
    return TestClient(main.app)


def _headers(actor="kavy", roles=None):
    roles = roles if roles is not None else []
    token, _ = main.auth_service.issue_token(actor, roles)
    return {"Authorization": f"Bearer {token}"}


def _certify(client, dataset_id="certifiable"):
    resp = client.post(
        "/certify",
        json={
            "dataset_id": dataset_id,
            "dataset_path": str(ROOT / "datasets" / "certifiable_sample.csv"),
            "metadata_path": str(ROOT / "datasets" / "metadata.json"),
        },
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "CERTIFIED"


def test_list_databases_requires_auth(client):
    resp = client.get("/databases")
    assert resp.status_code == 401


def test_list_databases_returns_eight_targets(client):
    resp = client.get("/databases", headers=_headers())
    assert resp.status_code == 200
    keys = {db["key"] for db in resp.json()}
    assert len(keys) == 8
    assert "VectorDB" in keys and "RelationalDB" in keys


def test_ingest_requires_auth(client):
    resp = client.post(
        "/ingest",
        json={"dataset_id": "x", "target_database": "RelationalDB", "source_format": "csv"},
    )
    assert resp.status_code == 401


def test_ingest_without_role_returns_403(client):
    _certify(client, "certifiable")
    resp = client.post(
        "/ingest",
        json={"dataset_id": "certifiable", "target_database": "RelationalDB", "source_format": "csv"},
        headers=_headers(roles=[]),
    )
    assert resp.status_code == 403


def test_ingest_uncertified_dataset_returns_422(client):
    resp = client.post(
        "/ingest",
        json={"dataset_id": "never-certified", "target_database": "RelationalDB", "source_format": "csv"},
        headers=_headers(roles=["ingest:relationaldb"]),
    )
    assert resp.status_code == 422
    assert "not CERTIFIED" in resp.json()["error"]["message"]


def test_ingest_certified_dataset_succeeds_and_is_retrievable(client):
    _certify(client, "certifiable")
    resp = client.post(
        "/ingest",
        json={"dataset_id": "certifiable", "target_database": "RelationalDB", "source_format": "csv"},
        headers=_headers(roles=["ingest:relationaldb"]),
    )
    assert resp.status_code == 201
    job = resp.json()
    assert job["status"] == "PERSISTED"
    assert job["target_database"] == "RelationalDB"

    fetched = client.get(f"/ingest/jobs/{job['job_id']}", headers=_headers())
    assert fetched.status_code == 200
    assert fetched.json()["job_id"] == job["job_id"]

    listed = client.get("/ingest/jobs", params={"dataset_id": "certifiable"}, headers=_headers())
    assert listed.status_code == 200
    assert len(listed.json()) == 1
