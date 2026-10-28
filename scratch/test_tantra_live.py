import json
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8000"

def req(method, path, body=None, headers=None):
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    data = json.dumps(body).encode("utf-8") if body else None
    r = urllib.request.Request(f"{BASE}{path}", data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))

print("=== 1. Auth Token Generation ===")
st, tok = req("POST", "/auth/token", {"actor": "TANTRA", "roles": ["ecosystem-reader"]})
print(f"Status: {st}")
print("Response:", json.dumps(tok, indent=2))
token = tok["access_token"]
auth_hdr = {"Authorization": f"Bearer {token}"}

print("\n=== 2. TANTRA Register Dataset (POST /tantra/datasets/register) ===")
reg_body = {
    "dataset_id": "BHIV-DS-MARITIME-AIS-LIVE-001",
    "dataset_version": "1.0",
    "schema_version": "1.0",
    "board": "maritime",
    "medium": "ais",
    "language": "en",
    "owner": "TANTRA",
    "actor": "tantra-orchestrator",
    "reason": "Live verification test via TANTRA runtime interface"
}
st, pkg = req("POST", "/tantra/datasets/register", reg_body)
print(f"Status: {st}")
print("Response:", json.dumps(pkg, indent=2))
pkg_id = pkg["package_id"]

print(f"\n=== 3. TANTRA Runtime Package Lookup (GET /tantra/packages/{pkg_id}/runtime) ===")
st, lookup = req("GET", f"/tantra/packages/{pkg_id}/runtime")
print(f"Status: {st}")
print("Response:", json.dumps(lookup, indent=2))

print("\n=== 4. TANTRA Capabilities Discovery (GET /tantra/capabilities) ===")
st, caps = req("GET", "/tantra/capabilities", headers=auth_hdr)
print(f"Status: {st}")
print(f"Discovered {len(caps)} capabilities. Sample first capability:")
print(json.dumps(caps[0], indent=2))

print("\n=== 5. TANTRA Capability Contract (GET /tantra/capabilities/cap-mangrove-monitoring/contract) ===")
st, contract = req("GET", "/tantra/capabilities/cap-mangrove-monitoring/contract", headers=auth_hdr)
print(f"Status: {st}")
print("Response:", json.dumps(contract, indent=2))

print("\n=== 6. TANTRA Capability Access Request (POST /tantra/access/request) ===")
acc_body = {
    "application_id": "TANTRA",
    "capability_id": "cap-mangrove-monitoring",
    "purpose": "environmental_monitoring"
}
st, grant = req("POST", "/tantra/access/request", acc_body, headers=auth_hdr)
print(f"Status: {st}")
print("Response:", json.dumps(grant, indent=2))
request_id = grant["request_id"]
grant_token = grant["access_token"]

print(f"\n=== 7. TANTRA Capability Data Retrieval (POST /tantra/capabilities/cap-mangrove-monitoring/retrieve) ===")
ret_body = {
    "application_id": "TANTRA",
    "access_token": grant_token,
    "query_params": {"region": "Sundarbans-North"}
}
st, data = req("POST", "/tantra/capabilities/cap-mangrove-monitoring/retrieve", ret_body, headers=auth_hdr)
print(f"Status: {st}")
print("Response:", json.dumps(data, indent=2))

print("\n=== 8. Traceability Audit Verification (GET /access/{request_id}) ===")
st, audit = req("GET", f"/access/{request_id}", headers=auth_hdr)
print(f"Status: {st}")
print("Response:", json.dumps(audit, indent=2))

print("\n=== 9. Security Enforcement: Denied Request - Unapproved Purpose (403 Forbidden) ===")
bad_purpose_body = {
    "application_id": "TANTRA",
    "capability_id": "cap-mangrove-monitoring",
    "purpose": "unapproved_crypto_mining"
}
st, err_purpose = req("POST", "/tantra/access/request", bad_purpose_body, headers=auth_hdr)
print(f"Status: {st}")
print("Response:", json.dumps(err_purpose, indent=2))

print("\n=== 10. Security Enforcement: Denied Request - Missing Authentication (401 Unauthorized) ===")
st, err_no_auth = req("GET", "/tantra/capabilities")
print(f"Status: {st}")
print("Response:", json.dumps(err_no_auth, indent=2))

print("\n=== 11. Security Enforcement: Denied Request - Token Replay by Another Actor (403 Forbidden) ===")
_, thief_tok = req("POST", "/auth/token", {"actor": "UNAUTHORIZED_ACTOR", "roles": ["ecosystem-reader"]})
thief_hdr = {"Authorization": f"Bearer {thief_tok['access_token']}"}
st, err_replay = req("POST", "/tantra/capabilities/cap-mangrove-monitoring/retrieve", ret_body, headers=thief_hdr)
print(f"Status: {st}")
print("Response:", json.dumps(err_replay, indent=2))
