from pathlib import Path
import pytest
from fastapi.testclient import TestClient

import main
from database_targets.models import IngestionFormat, TargetDatabase
from security.path_resolution import register_allowed_root
from services.artifact_store import ArtifactStore
from services.sql_artifact_store import SqlArtifactStore

ROOT = Path(__file__).resolve().parents[1]


def test_real_e2e_full_lifecycle(tmp_path):
    # Setup isolated stores & directories
    db_file = tmp_path / "e2e_test_target_store.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    store_dir = tmp_path / "ingestion_jobs"
    reports_dir = tmp_path / "reports"
    staging_dir = tmp_path / "upload_staging"
    datasets_dir = tmp_path / "datasets"

    reports_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)
    datasets_dir.mkdir(parents=True, exist_ok=True)

    register_allowed_root(datasets_dir)
    register_allowed_root(staging_dir)

    # Global service wiring for E2E
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

    # Step 1: Authentication - Login / Token Request
    token_resp = client.post(
        "/auth/token",
        json={"actor": "kavy", "roles": ["ingest:relationaldb", "operator"]},
    )
    assert token_resp.status_code == 200
    token_data = token_resp.json()
    token = token_data["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Step 2: Upload Initiation
    sample_bytes = (ROOT / "datasets" / "certifiable_sample.csv").read_bytes()
    dataset_id = "e2e_dataset_001"
    init_resp = client.post(
        "/upload",
        json={
            "filename": "certifiable_sample.csv",
            "content_type": "text/csv",
            "file_size": len(sample_bytes),
            "intended_use": "E2E Convergence Testing",
        },
        headers=headers,
    )
    assert init_resp.status_code == 201
    upload_id = init_resp.json()["upload_id"]

    # Step 3: Upload Content
    content_resp = client.post(
        f"/upload/{upload_id}/content",
        content=sample_bytes,
        headers=headers,
    )
    assert content_resp.status_code == 200

    # Step 4: Upload Validation
    val_resp = client.post(
        f"/upload/{upload_id}/validate",
        headers=headers,
    )
    assert val_resp.status_code == 200
    assert val_resp.json()["validation_passed"] is True

    # Step 5: Dataset Certification via POST /certify
    ds_file = datasets_dir / f"{dataset_id}.csv"
    ds_file.write_bytes(sample_bytes)

    cert_resp = client.post(
        "/certify",
        json={
            "dataset_id": dataset_id,
            "dataset_path": str(ds_file),
            "metadata_path": str(ROOT / "datasets" / "metadata.json"),
        },
    )
    assert cert_resp.status_code == 200
    assert cert_resp.json()["state"] == "CERTIFIED"

    # Step 6: Ingestion & Target Persistence via POST /ingest
    ingest_resp = client.post(
        "/ingest",
        json={
            "dataset_id": dataset_id,
            "target_database": "RelationalDB",
            "source_format": "csv",
            "upload_id": upload_id,
        },
        headers=headers,
    )
    assert ingest_resp.status_code == 201
    ingest_job = ingest_resp.json()
    assert ingest_job["status"] == "PERSISTED"

    # Step 7: Fresh-Session Target Persistence Verification
    del client
    fresh_sql_store = SqlArtifactStore(db_url, store_name="reports")
    fresh_router = main.DatabaseRouterService(
        certification_artifact_store=fresh_sql_store,
        store_dir=str(store_dir),
        target_store=fresh_sql_store,
        dataset_dir=str(datasets_dir),
    )

    summary = fresh_router.get_target_dataset(TargetDatabase.RELATIONAL_DB, dataset_id)
    assert summary is not None
    assert summary["record_count"] == 5
    assert summary["status"] == "PERSISTED"

    records = fresh_router.list_target_records(TargetDatabase.RELATIONAL_DB, dataset_id, limit=10)
    assert len(records) == 5
    assert records[0]["name"] == "John Doe"
    assert records[1]["name"] == "Alice Smith"

    # Step 8: Control Center / API Retrieval
    fresh_client = TestClient(main.app)
    job_get_resp = fresh_client.get(
        f"/ingest/jobs/{ingest_job['job_id']}",
        headers=headers,
    )
    assert job_get_resp.status_code == 200
    assert job_get_resp.json()["status"] == "PERSISTED"
