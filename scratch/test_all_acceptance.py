import requests
import json
import hashlib

BASE_URL = "https://bhiv-masterdb-ingestion-certification.onrender.com"

print("============================================================")
print("FINAL MASTERDB ACCEPTANCE VERIFICATION - LIVE SERVER TEST")
print("============================================================")

# Step 1: POST /auth/token
token_payload = {"actor": "kavy"}
token_res = requests.post(f"{BASE_URL}/auth/token", json=token_payload)
print(f"1. POST /auth/token status: {token_res.status_code}")
token_data = token_res.json()
print("Token Response:", json.dumps(token_data, indent=2))
token = token_data.get("access_token")
headers = {"Authorization": f"Bearer {token}"}

# Step 2: GET /databases
db_res = requests.get(f"{BASE_URL}/databases", headers=headers)
print(f"\n2. GET /databases status: {db_res.status_code}")
print("Databases:", json.dumps(db_res.json(), indent=2))

# Step 3: Prepare dataset and POST /upload
csv_content = """id,name,value
MASTERDB-FINAL-E2E-001,Rahil-Test,100
MASTERDB-FINAL-E2E-002,Rahil-Test-2,200
""".encode("utf-8")

sha256_checksum = hashlib.sha256(csv_content).hexdigest()

upload_init_payload = {
    "filename": "masterdb_final_e2e.csv",
    "content_type": "text/csv",
    "file_size": len(csv_content),
    "checksum_sha256": sha256_checksum,
    "intended_use": "Final Acceptance E2E Ingestion"
}
upload_init_res = requests.post(f"{BASE_URL}/upload", json=upload_init_payload, headers=headers)
print(f"\n3. POST /upload status: {upload_init_res.status_code}")
upload_init_data = upload_init_res.json()
print("Upload Init Response:", json.dumps(upload_init_data, indent=2))
upload_id = upload_init_data.get("upload_id")

# Step 4 & 5: POST /upload/{upload_id}/content
content_res = requests.post(
    f"{BASE_URL}/upload/{upload_id}/content",
    data=csv_content,
    headers={"Authorization": f"Bearer {token}", "Content-Type": "text/csv"}
)
print(f"\n4. POST /upload/{upload_id}/content status: {content_res.status_code}")
print("Upload Content Response:", json.dumps(content_res.json(), indent=2))

# Step 6: POST /upload/{upload_id}/validate
val_res = requests.post(f"{BASE_URL}/upload/{upload_id}/validate", headers=headers)
print(f"\n5. POST /upload/{upload_id}/validate status: {val_res.status_code}")
print("Upload Validate Response:", json.dumps(val_res.json(), indent=2))

# Check upload job status post-validation
up_job_val = requests.get(f"{BASE_URL}/upload/jobs/{upload_id}", headers=headers)
print(f"\nUpload Job Post-Validation status: {up_job_val.status_code}")
print(json.dumps(up_job_val.json(), indent=2))

# Step 8: POST /ingest
ingest_payload = {
    "dataset_id": "dataset_final_e2e_001",
    "target_database": "RelationalDB",
    "source_format": "csv",
    "upload_id": upload_id,
    "metadata": {
        "test_run": "FINAL_ACCEPTANCE_TEST",
        "author": "Rahil"
    }
}
ingest_res = requests.post(f"{BASE_URL}/ingest", json=ingest_payload, headers=headers)
print(f"\n6. POST /ingest status: {ingest_res.status_code}")
ingest_data = ingest_res.json()
print("Ingest Response:", json.dumps(ingest_data, indent=2))
job_id = ingest_data.get("job_id")

# Step 10: GET /ingest/jobs/{job_id}
if job_id:
    job_res = requests.get(f"{BASE_URL}/ingest/jobs/{job_id}", headers=headers)
    print(f"\n7. GET /ingest/jobs/{job_id} status: {job_res.status_code}")
    print(json.dumps(job_res.json(), indent=2))

# Step 11: GET /upload/jobs/{upload_id}
up_job_res = requests.get(f"{BASE_URL}/upload/jobs/{upload_id}", headers=headers)
print(f"\n8. GET /upload/jobs/{upload_id} status: {up_job_res.status_code}")
print(json.dumps(up_job_res.json(), indent=2))

