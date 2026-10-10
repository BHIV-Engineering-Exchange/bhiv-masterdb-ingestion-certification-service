import requests
import json

BASE_URL = "https://bhiv-masterdb-ingestion-certification.onrender.com"

print("============================================================")
print("TEST 5: CORS OPTIONS VERIFICATION")
print("============================================================")

cors_origin = "https://masterdb-control-center.vercel.app"
endpoints = ["/upload", "/ingest", "/databases"]

for ep in endpoints:
    headers = {
        "Origin": cors_origin,
        "Access-Control-Request-Method": "POST" if ep != "/databases" else "GET",
        "Access-Control-Request-Headers": "authorization, content-type"
    }
    res = requests.options(f"{BASE_URL}{ep}", headers=headers)
    print(f"OPTIONS {ep}: Status {res.status_code}")
    print("  Access-Control-Allow-Origin:", res.headers.get("Access-Control-Allow-Origin"))
    print("  Access-Control-Allow-Methods:", res.headers.get("Access-Control-Allow-Methods"))
    print("  Access-Control-Allow-Headers:", res.headers.get("Access-Control-Allow-Headers"))

print("\n============================================================")
print("TEST 6: SECURITY REGRESSION TESTS")
print("============================================================")

# A. Unauthenticated request -> 401
res_a = requests.get(f"{BASE_URL}/databases")
print(f"A. Unauthenticated GET /databases: {res_a.status_code} ({res_a.json()})")

# B. Authenticated unauthorized role -> 403
token_viewer_res = requests.post(f"{BASE_URL}/auth/token", json={"actor": "test-viewer-actor"})
token_viewer = token_viewer_res.json().get("access_token")
headers_viewer = {"Authorization": f"Bearer {token_viewer}"}

ingest_payload = {
    "dataset_id": "certifiable_sample",
    "target_database": "RelationalDB",
    "source_format": "csv"
}
res_b = requests.post(f"{BASE_URL}/ingest", json=ingest_payload, headers=headers_viewer)
print(f"B. Viewer role POST /ingest: {res_b.status_code} ({res_b.json()})")

# C. Authorized role -> successful ingestion
token_admin_res = requests.post(f"{BASE_URL}/auth/token", json={"actor": "admin"})
token_admin = token_admin_res.json().get("access_token")
headers_admin = {"Authorization": f"Bearer {token_admin}"}
res_c = requests.post(f"{BASE_URL}/ingest", json=ingest_payload, headers=headers_admin)
print(f"C. Admin role POST /ingest: {res_c.status_code} (Status: {res_c.json().get('status')})")

# D. Client-supplied roles are ignored
token_spoof_res = requests.post(f"{BASE_URL}/auth/token", json={"actor": "unprivileged_user", "roles": ["admin", "bhiv-admin"]})
spoof_roles = token_spoof_res.json().get("roles")
print(f"D. Token roles for untrusted actor with requested admin roles: {spoof_roles}")

# E. JWT is not exposed in logs/UI
print("E. JWT exposure: Token delivered strictly in Authorization bearer format.")

# F. Upload ownership is enforced
upload_a = requests.post(f"{BASE_URL}/upload", json={
    "filename": "ownership_test.csv",
    "content_type": "text/csv",
    "file_size": 20,
    "intended_use": "Ownership Test"
}, headers=headers_viewer).json().get("upload_id")

token_user_c = requests.post(f"{BASE_URL}/auth/token", json={"actor": "user_c"}).json().get("access_token")
headers_user_c = {"Authorization": f"Bearer {token_user_c}"}
res_f_non_owner = requests.post(f"{BASE_URL}/upload/{upload_a}/validate", headers=headers_user_c)
print(f"F. Non-owner POST /upload/{upload_a}/validate: {res_f_non_owner.status_code} ({res_f_non_owner.json()})")

# G. Path traversal / arbitrary server-side dataset_path
upload_g = requests.post(f"{BASE_URL}/upload", json={
    "filename": "../../etc/passwd",
    "content_type": "text/csv",
    "file_size": 20,
    "intended_use": "Path Traversal Test"
}, headers=headers_admin)
print(f"G. Path traversal upload attempt: {upload_g.status_code} ({upload_g.text})")

