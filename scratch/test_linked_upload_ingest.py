import requests
import json
import hashlib

BASE_URL = "https://bhiv-masterdb-ingestion-certification.onrender.com"

token_payload = {"actor": "kavy"}
token_res = requests.post(f"{BASE_URL}/auth/token", json=token_payload)
token = token_res.json().get("access_token")
headers = {"Authorization": f"Bearer {token}"}

# Create dataset in datasets directory on server if possible or upload and test dataset_id="certifiable_sample" with upload_id
csv_content = """id,name,age,email
101,John Doe,25,john@gmail.com
102,Alice Smith,30,alice@gmail.com
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
    "filename": "certifiable_sample.csv",
    "content_type": "text/csv",
    "file_size": len(csv_content),
    "checksum_sha256": sha256_checksum,
    "intended_use": "Final Acceptance E2E Ingestion",
    "provenance_metadata": prov_metadata,
    "metadata": prov_metadata
}
upload_init_res = requests.post(f"{BASE_URL}/upload", json=upload_init_payload, headers=headers)
upload_init_data = upload_init_res.json()
upload_id = upload_init_data.get("upload_id")
storage_path = upload_init_data.get("storage_path")

requests.post(f"{BASE_URL}/upload/{upload_id}/content", data=csv_content, headers={"Authorization": f"Bearer {token}", "Content-Type": "text/csv"})
requests.post(f"{BASE_URL}/upload/{upload_id}/validate", headers=headers)

cert_payload = {
    "dataset_id": "certifiable_sample",
    "dataset_path": "/opt/render/project/src/datasets/certifiable_sample.csv",
    "metadata_path": "/opt/render/project/src/datasets/metadata.json"
}
cert_res = requests.post(f"{BASE_URL}/certify", json=cert_payload, headers=headers)
print("Certify status:", cert_res.status_code)

# Now ingest dataset_id="certifiable_sample" AND upload_id=upload_id!
ingest_payload = {
    "dataset_id": "certifiable_sample",
    "target_database": "RelationalDB",
    "source_format": "csv",
    "upload_id": upload_id,
    "metadata": {
        "test_run": "FINAL_ACCEPTANCE_TEST",
        "author": "Rahil"
    }
}
ingest_res = requests.post(f"{BASE_URL}/ingest", json=ingest_payload, headers=headers)
print("\nIngest (dataset_id=certifiable_sample, upload_id=" + str(upload_id) + ") status:", ingest_res.status_code)
print("Ingest response:", json.dumps(ingest_res.json(), indent=2))

