from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main

ROOT = Path(__file__).resolve().parents[1]


from security.path_resolution import register_allowed_root


@pytest.fixture
def client(tmp_path) -> TestClient:
    # Fresh, isolated stores per test so certification/ingestion records
    # from other test modules never leak in.
    main.artifact_store.reports_dir = tmp_path / "reports"
    main.artifact_store.reports_dir.mkdir(parents=True, exist_ok=True)
    datasets_dir = tmp_path / "datasets"
    datasets_dir.mkdir(parents=True, exist_ok=True)
    register_allowed_root(datasets_dir)
    main.database_router_service = main.DatabaseRouterService(
        certification_artifact_store=main.artifact_store,
        store_dir=str(tmp_path / "ingestion_jobs"),
        dataset_dir=str(datasets_dir),
    )
    return TestClient(main.app), datasets_dir


def _headers(actor="kavy", roles=None):
    roles = roles if roles is not None else []
    token, _ = main.auth_service.issue_token(actor, roles)
    return {"Authorization": f"Bearer {token}"}


def _certify(client_info, dataset_id="certifiable"):
    client, datasets_dir = client_info
    sample_src = ROOT / "datasets" / "certifiable_sample.csv"
    ds_file = datasets_dir / f"{dataset_id}.csv"
    ds_file.write_bytes(sample_src.read_bytes())

    resp = client.post(
        "/certify",
        json={
            "dataset_id": dataset_id,
            "dataset_path": str(ds_file),
            "metadata_path": str(ROOT / "datasets" / "metadata.json"),
        },
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "CERTIFIED"


def test_list_databases_requires_auth(client):
    c, _ = client
    resp = c.get("/databases")
    assert resp.status_code == 401


def test_list_databases_returns_eight_targets(client):
    c, _ = client
    resp = c.get("/databases", headers=_headers())
    assert resp.status_code == 200
    keys = {db["key"] for db in resp.json()}
    assert len(keys) == 8
    assert "VectorDB" in keys and "RelationalDB" in keys


def test_ingest_requires_auth(client):
    c, _ = client
    resp = c.post(
        "/ingest",
        json={"dataset_id": "x", "target_database": "RelationalDB", "source_format": "csv"},
    )
    assert resp.status_code == 401


def test_ingest_without_role_returns_403(client):
    c, _ = client
    _certify(client, "certifiable")
    resp = c.post(
        "/ingest",
        json={"dataset_id": "certifiable", "target_database": "RelationalDB", "source_format": "csv"},
        headers=_headers(roles=[]),
    )
    assert resp.status_code == 403


def test_ingest_uncertified_dataset_returns_422(client):
    c, _ = client
    resp = c.post(
        "/ingest",
        json={"dataset_id": "never-certified", "target_database": "RelationalDB", "source_format": "csv"},
        headers=_headers(roles=["ingest:relationaldb"]),
    )
    assert resp.status_code == 422
    assert "not CERTIFIED" in resp.json()["error"]["message"]


def test_ingest_certified_dataset_succeeds_and_is_retrievable(client):
    c, _ = client
    _certify(client, "certifiable")
    resp = c.post(
        "/ingest",
        json={"dataset_id": "certifiable", "target_database": "RelationalDB", "source_format": "csv"},
        headers=_headers(roles=["ingest:relationaldb"]),
    )
    assert resp.status_code == 201
    job = resp.json()
    assert job["status"] == "PERSISTED"
    assert job["target_database"] == "RelationalDB"

    fetched = c.get(f"/ingest/jobs/{job['job_id']}", headers=_headers())
    assert fetched.status_code == 200
    assert fetched.json()["job_id"] == job["job_id"]

    listed = c.get("/ingest/jobs", params={"dataset_id": "certifiable"}, headers=_headers())
    assert listed.status_code == 200
    assert len(listed.json()) == 1
