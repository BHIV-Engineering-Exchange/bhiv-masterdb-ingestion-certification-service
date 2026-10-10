import requests
import json
import hashlib

BASE_URL = "https://bhiv-masterdb-ingestion-certification.onrender.com"

print("--- STARTING LIVE BACKEND E2E TEST ---")

# 1. POST /auth/token
token_payload = {
    "actor": "Rahil-Test",
    "roles": ["ingest:relationaldb", "ingest:vectordb", "ingest:graphdb", "operator", "admin"]
}
token_res = requests.post(f"{BASE_URL}/auth/token", json=token_payload)
print(f"1. POST /auth/token: {token_res.status_code}")
print(token_res.json())
token = token_res.json().get("access_token")
headers = {"Authorization": f"Bearer {token}"}

# 2. GET /databases
db_res = requests.get(f"{BASE_URL}/databases", headers=headers)
print(f"2. GET /databases: {db_res.status_code}")
print(db_res.json())

# 3. POST /upload
csv_content = """id,name,value
MASTERDB-FINAL-E2E-001,Rahil-Test,100
MASTERDB-FINAL-E2E-002,Rahil-Test-2,200
""".encode("utf-8")

sha256_checksum = hashlib.sha256(csv_content).hexdigest()

upload_init_payload = {
    "filename": "masterdb_final_e2e.csv",
    "content_type": "text/csv",
    "file_size": len(csv_content),
    "checksum": sha256_checksum,
    "intended_use": "Final Acceptance E2E Ingestion"
}
upload_init_res = requests.post(f"{BASE_URL}/upload", json=upload_init_payload, headers=headers)
print(f"3. POST /upload: {upload_init_res.status_code}")
print(upload_init_res.json())
upload_data = upload_init_res.json()
upload_id = upload_data.get("upload_id")

# 4. POST /upload/{upload_id}/content
content_res = requests.post(
    f"{BASE_URL}/upload/{upload_id}/content",
    data=csv_content,
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"}
)
print(f"4. POST /upload/content: {content_res.status_code}")
print(content_res.json())

# 5. POST /upload/{upload_id}/validate
val_res = requests.post(f"{BASE_URL}/upload/{upload_id}/validate", headers=headers)
print(f"5. POST /upload/validate: {val_res.status_code}")
print(val_res.json())

# Check upload job status after validation
up_job_val = requests.get(f"{BASE_URL}/upload/jobs/{upload_id}", headers=headers)
print(f"Upload job post-validation: {up_job_val.status_code}")
print(up_job_val.json())

# 6. POST /ingest
ingest_payload = {
    "dataset_id": "dataset_final_e2e_001",
    "target_database": "PostgreSQL", # or "relationaldb" / "TargetDatabase.POSTGRESQL" / whatever targets /databases returned
    "source_format": "CSV",
    "upload_id": upload_id,
    "metadata": {
        "test_run": "FINAL_ACCEPTANCE_TEST",
        "author": "Rahil"
    }
}
ingest_res = requests.post(f"{BASE_URL}/ingest", json=ingest_payload, headers=headers)
print(f"6. POST /ingest: {ingest_res.status_code}")
print(ingest_res.json())
ingest_data = ingest_res.json()
job_id = ingest_data.get("job_id")

# 7. GET /ingest/jobs/{job_id}
if job_id:
    job_res = requests.get(f"{BASE_URL}/ingest/jobs/{job_id}", headers=headers)
    print(f"7. GET /ingest/jobs/{job_id}: {job_res.status_code}")
    print(json.dumps(job_res.json(), indent=2))

# 8. GET /upload/jobs/{upload_id}
up_job_res = requests.get(f"{BASE_URL}/upload/jobs/{upload_id}", headers=headers)
print(f"8. GET /upload/jobs/{upload_id}: {up_job_res.status_code}")
print(json.dumps(up_job_res.json(), indent=2))

