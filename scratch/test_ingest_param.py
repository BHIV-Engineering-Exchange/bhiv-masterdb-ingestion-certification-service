import requests
import json
import hashlib

BASE_URL = "https://bhiv-masterdb-ingestion-certification.onrender.com"

# 1. Auth token
token_payload = {"actor": "kavy"}
token_res = requests.post(f"{BASE_URL}/auth/token", json=token_payload)
token = token_res.json().get("access_token")
headers = {"Authorization": f"Bearer {token}"}

# 2. Upload dataset matching certifiable_sample schema
csv_content = """id,name,age,email
101,John Doe,25,john@gmail.com
102,Alice Smith,30,alice@gmail.com
103,Bob Johnson,22,bob@gmail.com
104,Emma Wilson,28,emma@gmail.com
105,Michael Brown,35,michael@gmail.com
""".encode("utf-8")

sha256_checksum = hashlib.sha256(csv_content).hexdigest()

prov_metadata = {
    "dataset_name": "Customer Dataset",
    "owner": "MASTERDB",
    "source": "Internal System",
    "license": "MIT",
    "version": "1.0",
    "lineage": "Raw Customer Data",
    "transformation_log": "Initial Import"
}

upload_init_payload = {
    "filename": "masterdb_final_e2e.csv",
    "content_type": "text/csv",
    "file_size": len(csv_content),
    "checksum_sha256": sha256_checksum,
    "intended_use": "Final Acceptance E2E Ingestion",
    "provenance_metadata": prov_metadata,
    "metadata": prov_metadata
}
upload_init_res = requests.post(f"{BASE_URL}/upload", json=upload_init_payload, headers=headers)
upload_init_data = upload_init_res.json()
print("1. Upload Init Status:", upload_init_res.status_code)
print(upload_init_data)
upload_id = upload_init_data.get("upload_id")
storage_path = upload_init_data.get("storage_path")

# Content
content_res = requests.post(
    f"{BASE_URL}/upload/{upload_id}/content",
    data=csv_content,
    headers={"Authorization": f"Bearer {token}", "Content-Type": "text/csv"}
)
print("2. Upload Content Status:", content_res.status_code)

# Validate
val_res = requests.post(f"{BASE_URL}/upload/{upload_id}/validate", headers=headers)
print("3. Upload Validate Status:", val_res.status_code)

# Certify
cert_payload = {
    "dataset_id": upload_id,
    "dataset_path": storage_path,
    "metadata_path": "/opt/render/project/src/datasets/metadata.json"
}
cert_res = requests.post(f"{BASE_URL}/certify", json=cert_payload, headers=headers)
print("4. Certify Response status:", cert_res.status_code)
print("Certify Response state:", cert_res.json().get("state"))

# Ingest without upload_id parameter first
ingest_payload_1 = {
    "dataset_id": upload_id,
    "target_database": "RelationalDB",
    "source_format": "csv",
    "metadata": {
        "test_run": "FINAL_ACCEPTANCE_TEST",
        "author": "Rahil"
    }
}
ingest_res_1 = requests.post(f"{BASE_URL}/ingest", json=ingest_payload_1, headers=headers)
print("\n5. Ingest (without upload_id param) status:", ingest_res_1.status_code)
print("Ingest response:", json.dumps(ingest_res_1.json(), indent=2))

# Ingest with upload_id parameter
ingest_payload_2 = {
    "dataset_id": upload_id,
    "target_database": "RelationalDB",
    "source_format": "csv",
    "upload_id": upload_id,
    "metadata": {
        "test_run": "FINAL_ACCEPTANCE_TEST",
        "author": "Rahil"
    }
}
ingest_res_2 = requests.post(f"{BASE_URL}/ingest", json=ingest_payload_2, headers=headers)
print("\n6. Ingest (with upload_id param) status:", ingest_res_2.status_code)
print("Ingest response:", json.dumps(ingest_res_2.json(), indent=2))

