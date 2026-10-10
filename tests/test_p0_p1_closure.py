"""
Tests for P0 Upload Lifecycle Completion and P1 Target Database HTTP Read-back.
"""
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

import main
from security.path_resolution import register_allowed_root
from services.sql_artifact_store import SqlArtifactStore

METADATA_JSON = {
    "dataset_name": "Customer Dataset",
    "owner": "MASTERDB",
    "source": "Internal System",
    "license": "MIT",
    "version": "1.0",
    "lineage": "Raw Customer Data",
    "transformation_log": "Initial Import"
}


def test_p0_upload_lifecycle_completion(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_PASSWORD", "test-admin-password")
    """Verify upload lifecycle transitions from VALIDATED -> REGISTERED -> INGESTED -> AVAILABLE."""
    db_file = tmp_path / "p0_test.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    store_dir = tmp_path / "ingestion_jobs"
    staging_dir = tmp_path / "upload_staging"
    datasets_dir = tmp_path / "datasets"

    staging_dir.mkdir(parents=True, exist_ok=True)
    datasets_dir.mkdir(parents=True, exist_ok=True)
    register_allowed_root(datasets_dir)
    register_allowed_root(staging_dir)

    meta_file = datasets_dir / "metadata.json"
    meta_file.write_text(json.dumps(METADATA_JSON))

    sql_store = SqlArtifactStore(db_url, store_name="reports")
    main.artifact_store = sql_store
    main.upload_service = main.UploadService(staging_dir=str(staging_dir))
    main.validation_service = main.ValidationService(artifact_store=sql_store)
    main.certification_service = main.CertificationService(
        validation_service=main.validation_service,
        artifact_store=sql_store,
    )
    main.database_router_service = main.DatabaseRouterService(
        certification_artifact_store=sql_store,
        store_dir=str(store_dir),
        target_store=sql_store,
        upload_service=main.upload_service,
        certification_service=main.certification_service,
        dataset_dir=str(datasets_dir),
    )

    client = TestClient(main.app)

    # Auth
    token_resp = client.post(
        "/auth/token",
        json={"actor": "admin", "password": "test-admin-password"},
    )
    token = token_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Upload initiation
    sample_csv = "id,name,age,email\n1,Alice,30,alice@example.com\n2,Bob,25,bob@example.com\n"
    sample_bytes = sample_csv.encode("utf-8")

    init_resp = client.post(
        "/upload",
        json={
            "filename": "certifiable_sample.csv",
            "content_type": "text/csv",
            "file_size": len(sample_bytes),
            "intended_use": "P0 Test",
        },
        headers=headers,
    )
    assert init_resp.status_code == 201
    upload_id = init_resp.json()["upload_id"]

    # Content
    content_resp = client.post(
        f"/upload/{upload_id}/content",
        content=sample_bytes,
        headers=headers,
    )
    assert content_resp.status_code == 200

    # Validate
    val_resp = client.post(f"/upload/{upload_id}/validate", headers=headers)
    assert val_resp.status_code == 200

    # Certify dataset
    cert_file = datasets_dir / "certifiable_sample.csv"
    cert_file.write_bytes(sample_bytes)
    cert_resp = client.post(
        "/certify",
        json={"dataset_id": "certifiable_sample", "dataset_path": str(cert_file), "metadata_path": str(meta_file)},
        headers=headers,
    )
    assert cert_resp.status_code == 200
    assert cert_resp.json()["state"] == "CERTIFIED"

    # Ingest
    ingest_resp = client.post(
        "/ingest",
        json={
            "dataset_id": "certifiable_sample",
            "target_database": "RelationalDB",
            "source_format": "csv",
            "upload_id": upload_id,
        },
        headers=headers,
    )
    assert ingest_resp.status_code == 201
    ingest_data = ingest_resp.json()
    assert ingest_data["status"] == "PERSISTED"
    ingestion_job_id = ingest_data["job_id"]

    # Verify upload job is now AVAILABLE
    up_resp = client.get(f"/upload/jobs/{upload_id}", headers=headers)
    assert up_resp.status_code == 200
    up_data = up_resp.json()
    assert up_data["status"] == "AVAILABLE"
    assert up_data["dataset_id"] == "certifiable_sample"
    assert up_data["ingestion_job_id"] == ingestion_job_id
    assert up_data["timestamps"]["registered_at"] is not None
    assert up_data["timestamps"]["ingested_at"] is not None
    assert up_data["timestamps"]["available_at"] is not None


def test_p1_target_database_http_readback(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_PASSWORD", "test-admin-password")
    """Verify P1 endpoint GET /databases/{target_database}/records/{dataset_id} returns persisted records."""
    db_file = tmp_path / "p1_test.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    store_dir = tmp_path / "ingestion_jobs"
    staging_dir = tmp_path / "upload_staging"
    datasets_dir = tmp_path / "datasets"

    staging_dir.mkdir(parents=True, exist_ok=True)
    datasets_dir.mkdir(parents=True, exist_ok=True)
    register_allowed_root(datasets_dir)
    register_allowed_root(staging_dir)

    meta_file = datasets_dir / "metadata.json"
    meta_file.write_text(json.dumps(METADATA_JSON))

    sql_store = SqlArtifactStore(db_url, store_name="reports")
    main.artifact_store = sql_store
    main.upload_service = main.UploadService(staging_dir=str(staging_dir))
    main.validation_service = main.ValidationService(artifact_store=sql_store)
    main.certification_service = main.CertificationService(
        validation_service=main.validation_service,
        artifact_store=sql_store,
    )
    main.database_router_service = main.DatabaseRouterService(
        certification_artifact_store=sql_store,
        store_dir=str(store_dir),
        target_store=sql_store,
        upload_service=main.upload_service,
        certification_service=main.certification_service,
        dataset_dir=str(datasets_dir),
    )

    client = TestClient(main.app)

    # Auth
    token_resp = client.post(
        "/auth/token",
        json={"actor": "admin", "password": "test-admin-password"},
    )
    token = token_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Upload & Ingest
    sample_csv = "id,name,age,email\n101,John Doe,25,john@example.com\n102,Alice Smith,30,alice@example.com\n"
    sample_bytes = sample_csv.encode("utf-8")
    dataset_id = "test_readback_ds"

    ds_file = datasets_dir / f"{dataset_id}.csv"
    ds_file.write_bytes(sample_bytes)

    cert_resp = client.post(
        "/certify",
        json={"dataset_id": dataset_id, "dataset_path": str(ds_file), "metadata_path": str(meta_file)},
        headers=headers,
    )
    assert cert_resp.status_code == 200
    assert cert_resp.json()["state"] == "CERTIFIED"

    ingest_resp = client.post(
        "/ingest",
        json={
            "dataset_id": dataset_id,
            "target_database": "RelationalDB",
            "source_format": "csv",
        },
        headers=headers,
    )
    assert ingest_resp.status_code == 201

    # Call P1 Read-back HTTP Endpoint
    readback_resp = client.get(f"/databases/RelationalDB/records/{dataset_id}", headers=headers)
    assert readback_resp.status_code == 200
    readback_data = readback_resp.json()
    assert readback_data["target_database"] == "RelationalDB"
    assert readback_data["dataset_id"] == dataset_id
    assert readback_data["count"] == 2
    assert len(readback_data["records"]) == 2
    assert readback_data["records"][0]["name"] == "John Doe"
    assert readback_data["records"][1]["name"] == "Alice Smith"
