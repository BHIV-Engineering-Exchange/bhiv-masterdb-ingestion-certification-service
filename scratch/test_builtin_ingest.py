import requests
import json

BASE_URL = "https://bhiv-masterdb-ingestion-certification.onrender.com"

# 1. Auth token
token_payload = {"actor": "kavy"}
token_res = requests.post(f"{BASE_URL}/auth/token", json=token_payload)
token = token_res.json().get("access_token")
headers = {"Authorization": f"Bearer {token}"}

# Certify built-in certifiable_sample
cert_payload = {
    "dataset_id": "certifiable_sample",
    "dataset_path": "/opt/render/project/src/datasets/certifiable_sample.csv",
    "metadata_path": "/opt/render/project/src/datasets/metadata.json"
}
cert_res = requests.post(f"{BASE_URL}/certify", json=cert_payload, headers=headers)
print("Certify status:", cert_res.status_code)
print("Certify response:", json.dumps(cert_res.json(), indent=2))

# Ingest certifiable_sample
ingest_payload = {
    "dataset_id": "certifiable_sample",
    "target_database": "RelationalDB",
    "source_format": "csv",
    "metadata": {
        "test_run": "FINAL_ACCEPTANCE_TEST",
        "author": "Rahil"
    }
}
ingest_res = requests.post(f"{BASE_URL}/ingest", json=ingest_payload, headers=headers)
print("\nIngest status:", ingest_res.status_code)
print("Ingest response:", json.dumps(ingest_res.json(), indent=2))

