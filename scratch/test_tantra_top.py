import json
import urllib.request

BASE = "http://127.0.0.1:8000"

def p(path, b, h=None):
    headers = {"Content-Type": "application/json"}
    if h: headers.update(h)
    data = json.dumps(b).encode()
    r = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method="POST")
    with urllib.request.urlopen(r) as resp:
        return resp.status, json.loads(resp.read().decode())

def g(path, h=None):
    r = urllib.request.Request(f"{BASE}{path}", headers=h or {})
    with urllib.request.urlopen(r) as resp:
        return resp.status, json.loads(resp.read().decode())

st, tok = p("/auth/token", {"actor": "TANTRA", "roles": ["ecosystem-reader"]})
print("=== 1. TOKEN ===")
print(json.dumps(tok, indent=2))

reg = {
    "dataset_id": "BHIV-DS-MARITIME-AIS-LIVE-002",
    "dataset_version": "1.0",
    "schema_version": "1.0",
    "board": "maritime",
    "medium": "ais",
    "language": "en",
    "owner": "TANTRA",
    "actor": "tantra-orchestrator",
    "reason": "Live verification test"
}
st, pkg = p("/tantra/datasets/register", reg)
print("=== 2. REGISTER ===")
print(json.dumps(pkg, indent=2))

pkg_id = pkg["package_id"]
st, lkp = g(f"/tantra/packages/{pkg_id}/runtime")
print("=== 3. LOOKUP ===")
print(json.dumps(lkp, indent=2))
