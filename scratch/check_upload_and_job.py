import requests
import json

BASE_URL = "https://bhiv-masterdb-ingestion-certification.onrender.com"

token_payload = {"actor": "kavy"}
token_res = requests.post(f"{BASE_URL}/auth/token", json=token_payload)
token = token_res.json().get("access_token")
headers = {"Authorization": f"Bearer {token}"}

upload_id = "upl-882301b91149"
job_id = "ingest-7f6122f1f01c"

up_res = requests.get(f"{BASE_URL}/upload/jobs/{upload_id}", headers=headers)
print("=== GET /upload/jobs/{upload_id} ===")
print("Status:", up_res.status_code)
print(json.dumps(up_res.json(), indent=2))

ing_res = requests.get(f"{BASE_URL}/ingest/jobs/{job_id}", headers=headers)
print("\n=== GET /ingest/jobs/{job_id} ===")
print("Status:", ing_res.status_code)
print(json.dumps(ing_res.json(), indent=2))

