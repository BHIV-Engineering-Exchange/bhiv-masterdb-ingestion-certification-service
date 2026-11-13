import json
import urllib.request
import urllib.error

BASE_URL = "https://bhiv-masterdb-ingestion-certification.onrender.com"

def call_api(method, path, body=None):
    url = f"{BASE_URL}{path}"
    headers = {"User-Agent": "Antigravity/1.0"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode()
            try:
                parsed = json.loads(content)
            except Exception:
                parsed = content
            return resp.status, parsed
    except urllib.error.HTTPError as e:
        err_content = e.read().decode()
        try:
            parsed = json.loads(err_content)
        except Exception:
            parsed = err_content
        return e.code, parsed

flow_records = []

# Step 1: Health
status, data = call_api("GET", "/health")
flow_records.append({"step": 1, "action": "GET /health", "status": status, "data": data})

# Step 2: Register package via TANTRA interface
dataset_id = "ds-synthetic-tantra-golden-001"
reg_payload = {
    "dataset_id": dataset_id,
    "dataset_version": "1.0.0",
    "schema_version": "1.0.0",
    "board": "synthetic-tantra",
    "medium": "api",
    "language": "en",
    "owner": "tantra_lead",
    "actor": "tantra_façade",
    "reason": "Golden path synthetic test registration.",
}
status, data = call_api("POST", "/tantra/datasets/register", reg_payload)
pkg_id = data.get("package_id")
flow_records.append({"step": 2, "action": "POST /tantra/datasets/register", "status": status, "package_id": pkg_id, "data": data})

# Step 3: Get Package detail
status, data = call_api("GET", f"/packages/{pkg_id}")
flow_records.append({"step": 3, "action": f"GET /packages/{pkg_id}", "status": status, "data": data})

# Step 4: Initial readiness (should be NOT_RETRIEVABLE)
status, data = call_api("GET", f"/tantra/packages/{pkg_id}/retrieval-readiness")
flow_records.append({"step": 4, "action": f"GET /tantra/packages/{pkg_id}/retrieval-readiness", "status": status, "readiness": data.get("status"), "data": data})

# Step 5: Promote REGISTERED -> INGESTED
status, data = call_api("POST", "/packages/promote", {
    "package_id": pkg_id, "to_status": "INGESTED", "actor": "tantra_runner", "reason": "Ingested."
})
flow_records.append({"step": 5, "action": "POST /packages/promote -> INGESTED", "status": status, "data": data})

# Step 6: Promote INGESTED -> VALIDATED
status, data = call_api("POST", "/packages/promote", {
    "package_id": pkg_id, "to_status": "VALIDATED", "actor": "tantra_runner", "reason": "Validated."
})
flow_records.append({"step": 6, "action": "POST /packages/promote -> VALIDATED", "status": status, "data": data})

# Step 7: Link Knowledge Object with lineage
ko_payload = {
    "package_id": pkg_id,
    "source_reference": "src-gev-celestrak",
    "derivation_path": ["synthetic_raw", "synthetic_validated"]
}
status, data = call_api("POST", f"/packages/{pkg_id}/knowledge-object", ko_payload)
flow_records.append({"step": 7, "action": f"POST /packages/{pkg_id}/knowledge-object", "status": status, "data": data})

# Step 8: Verify Lineage
status, data = call_api("GET", f"/packages/{pkg_id}/lineage")
flow_records.append({"step": 8, "action": f"GET /packages/{pkg_id}/lineage", "status": status, "data": data})

# Step 9: Promote VALIDATED -> VERIFIED
status, data = call_api("POST", "/packages/promote", {
    "package_id": pkg_id, "to_status": "VERIFIED", "actor": "tantra_runner", "reason": "Verified."
})
flow_records.append({"step": 9, "action": "POST /packages/promote -> VERIFIED", "status": status, "data": data})

# Step 10: Promote VERIFIED -> CERTIFIED
status, data = call_api("POST", "/packages/promote", {
    "package_id": pkg_id, "to_status": "CERTIFIED", "actor": "tantra_runner", "reason": "Certified."
})
flow_records.append({"step": 10, "action": "POST /packages/promote -> CERTIFIED", "status": status, "data": data})

# Step 11: Promote CERTIFIED -> RETRIEVAL_READY
status, data = call_api("POST", "/packages/promote", {
    "package_id": pkg_id, "to_status": "RETRIEVAL_READY", "actor": "tantra_runner", "reason": "Retrieval ready."
})
flow_records.append({"step": 11, "action": "POST /packages/promote -> RETRIEVAL_READY", "status": status, "data": data})

# Step 12: Verify retrieval readiness -> CERTIFIED_RETRIEVABLE
status, data = call_api("GET", f"/tantra/packages/{pkg_id}/retrieval-readiness")
flow_records.append({"step": 12, "action": f"GET /tantra/packages/{pkg_id}/retrieval-readiness", "status": status, "readiness": data.get("status"), "data": data})

# Step 13: Discovery filter
status, data = call_api("GET", f"/discovery/packages?package_id={pkg_id}")
flow_records.append({"step": 13, "action": f"GET /discovery/packages?package_id={pkg_id}", "status": status, "count": data.get("count"), "data": data})

# Step 14: TANTRA runtime lookup
status, data = call_api("GET", f"/tantra/packages/{pkg_id}/runtime")
flow_records.append({"step": 14, "action": f"GET /tantra/packages/{pkg_id}/runtime", "status": status, "data": data})

# Step 15: Audit report
status, data = call_api("GET", f"/packages/{pkg_id}/audit")
flow_records.append({"step": 15, "action": f"GET /packages/{pkg_id}/audit", "status": status, "complete": data.get("complete"), "data": data})

# Step 16: State replay
status, data = call_api("GET", f"/packages/{pkg_id}/replay")
flow_records.append({"step": 16, "action": f"GET /packages/{pkg_id}/replay", "status": status, "replay_consistent": data.get("replay_consistent"), "replayed_status": data.get("replayed_status"), "data": data})

# Step 17: Deprecate package
status, data = call_api("POST", "/packages/deprecate", {
    "package_id": pkg_id, "actor": "tantra_runner", "reason": "End of test deprecation."
})
flow_records.append({"step": 17, "action": "POST /packages/deprecate", "status": status, "package_status": data.get("status"), "data": data})

# Step 18: Verify retrieval readiness dropped to NOT_RETRIEVABLE
status, data = call_api("GET", f"/tantra/packages/{pkg_id}/retrieval-readiness")
flow_records.append({"step": 18, "action": f"GET /tantra/packages/{pkg_id}/retrieval-readiness (after deprecate)", "status": status, "readiness": data.get("status"), "data": data})

# Step 19: Promote DEPRECATED -> ARCHIVED
status, data = call_api("POST", "/packages/promote", {
    "package_id": pkg_id, "to_status": "ARCHIVED", "actor": "tantra_runner", "reason": "Archived."
})
flow_records.append({"step": 19, "action": "POST /packages/promote -> ARCHIVED", "status": status, "package_status": data.get("status"), "data": data})

# Step 20: Negative test - Illegal transition from terminal ARCHIVED -> INGESTED
status, data = call_api("POST", "/packages/promote", {
    "package_id": pkg_id, "to_status": "INGESTED", "actor": "tantra_runner", "reason": "Illegal revive."
})
flow_records.append({"step": 20, "action": "POST /packages/promote (ARCHIVED -> INGESTED, expect 400)", "status": status, "error": data})

# Step 21: Negative test - Unknown package
status, data = call_api("GET", "/packages/pkg-unknown-000000000000")
flow_records.append({"step": 21, "action": "GET /packages/pkg-unknown (expect 404)", "status": status, "error": data})

# Step 22: Negative test - Knowledge object with non-existent parent package
status, data = call_api("POST", f"/packages/{pkg_id}/knowledge-object", {
    "package_id": pkg_id,
    "parent_package": "pkg-does-not-exist",
    "source_reference": "src-test"
})
flow_records.append({"step": 22, "action": "POST /knowledge-object with missing parent (expect 400)", "status": status, "error": data})

for r in flow_records:
    print(f"Step {r['step']}: {r['action']} -> HTTP {r['status']}")

with open("scratch/deployed_synthetic_flow_evidence.json", "w") as f:
    json.dump(flow_records, f, indent=2)

print("\nSaved scratch/deployed_synthetic_flow_evidence.json")
