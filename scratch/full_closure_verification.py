import sys
sys.path.insert(0, ".")
import json
import hashlib
from pathlib import Path
from fastapi.testclient import TestClient

import main
from security.path_resolution import register_allowed_root
from services.sql_artifact_store import SqlArtifactStore

print("============================================================")
print("FINAL END-TO-END CLOSURE VERIFICATION")
print("============================================================")

tmp_dir = Path("scratch/e2e_run").resolve()
tmp_dir.mkdir(parents=True, exist_ok=True)

db_file = tmp_dir / "closure_e2e.db"
db_url = f"sqlite:///{db_file.as_posix()}"
store_dir = tmp_dir / "ingestion_jobs"
staging_dir = tmp_dir / "upload_staging"
datasets_dir = tmp_dir / "datasets"

staging_dir.mkdir(parents=True, exist_ok=True)
datasets_dir.mkdir(parents=True, exist_ok=True)
register_allowed_root(datasets_dir)
register_allowed_root(staging_dir)

metadata_json = {
    "dataset_name": "Customer Dataset",
    "owner": "MASTERDB",
    "source": "Internal System",
    "license": "MIT",
    "version": "1.0",
    "lineage": "Raw Customer Data",
    "transformation_log": "Initial Import"
}

meta_file = datasets_dir / "metadata.json"
meta_file.write_text(json.dumps(metadata_json))

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

# 1. POST /auth/token
token_res = client.post("/auth/token", json={"actor": "admin"})
token = token_res.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}
print(f"1. Auth Token Issued for 'admin' (Roles: {token_res.json()['roles']})")

# 2. GET /databases
db_res = client.get("/databases", headers=headers)
print(f"2. Databases Discovered: {len(db_res.json())} targets")

# 3. Prepare CSV and POST /upload
csv_content = """id,name,age,email
101,MASTERDB-FINAL-E2E-001,30,rahil-test-1@masterdb.com
102,MASTERDB-FINAL-E2E-002,32,rahil-test-2@masterdb.com
""".encode("utf-8")

sha256_checksum = hashlib.sha256(csv_content).hexdigest()

upload_init_res = client.post(
    "/upload",
    json={
        "filename": "masterdb_final_closure.csv",
        "content_type": "text/csv",
        "file_size": len(csv_content),
        "checksum_sha256": sha256_checksum,
        "intended_use": "Final Acceptance E2E Ingestion",
    },
    headers=headers,
)
upload_id = upload_init_res.json()["upload_id"]
print(f"3. Upload Initiated: upload_id={upload_id}, status={upload_init_res.json()['status']}")

# 4. Content Transfer
content_res = client.post(
    f"/upload/{upload_id}/content",
    content=csv_content,
    headers={"Authorization": f"Bearer {token}", "Content-Type": "text/csv"},
)
print(f"4. Upload Content Staged: status={content_res.json()['status']}, bytes={content_res.json()['file_size_bytes']}")

# 5. Validation
val_res = client.post(f"/upload/{upload_id}/validate", headers=headers)
print(f"5. Upload Validated: status={val_res.json()['status']}, passed={val_res.json()['validation_passed']}")

# 6. Certification
dataset_id = "masterdb_final_closure"
ds_file = datasets_dir / f"{dataset_id}.csv"
ds_file.write_bytes(csv_content)

cert_res = client.post(
    "/certify",
    json={
        "dataset_id": dataset_id,
        "dataset_path": str(ds_file),
        "metadata_path": str(meta_file),
    },
    headers=headers,
)
print(f"6. Dataset Certified: dataset_id={dataset_id}, state={cert_res.json()['state']}, score={cert_res.json()['report']['integrity_score']}")

# 7. Ingestion
ingest_res = client.post(
    "/ingest",
    json={
        "dataset_id": dataset_id,
        "target_database": "RelationalDB",
        "source_format": "csv",
        "upload_id": upload_id,
        "metadata": {
            "test_run": "FINAL_CLOSURE_RUN",
            "author": "Rahil"
        }
    },
    headers=headers,
)
ingest_data = ingest_res.json()
job_id = ingest_data["job_id"]
print(f"7. Dataset Ingested: job_id={job_id}, status={ingest_data['status']}, target_ref={ingest_data['metadata']['target_reference']}")

# 8. Retrieve Upload Job Status (P0 Proof)
up_job_res = client.get(f"/upload/jobs/{upload_id}", headers=headers)
up_job_data = up_job_res.json()
print("\n8. Upload Job Final Status (P0 Proof):")
print(json.dumps(up_job_data, indent=2))

# 9. Retrieve Ingestion Job
ing_job_res = client.get(f"/ingest/jobs/{job_id}", headers=headers)
print("\n9. Ingestion Job Status:")
print(json.dumps(ing_job_res.json(), indent=2))

# 10. HTTP Target Database Read-Back (P1 Proof)
readback_res = client.get(f"/databases/RelationalDB/records/{dataset_id}", headers=headers)
readback_data = readback_res.json()
print("\n10. HTTP Target Database Read-Back (P1 Proof):")
print(json.dumps(readback_data, indent=2))

