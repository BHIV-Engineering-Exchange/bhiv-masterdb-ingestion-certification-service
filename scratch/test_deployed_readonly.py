import json
import urllib.request
import urllib.error

BASE_URL = "https://bhiv-masterdb-ingestion-certification.onrender.com"

endpoints = [
    "/health",
    "/ready",
    "/runtime/identity",
    "/metrics",
    "/discovery/packages",
    "/capabilities",
    "/sources",
    "/mdu/status",
    "/shared/registry",
    "/databases",
    "/bcaes/registries",
    "/canonical-repository/documents",
]

results = []
for ep in endpoints:
    url = f"{BASE_URL}{ep}"
    req = urllib.request.Request(url, headers={"User-Agent": "Antigravity/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode()
            status = resp.status
            try:
                parsed = json.loads(body)
                summary = f"JSON keys/length: {list(parsed.keys()) if isinstance(parsed, dict) else len(parsed)}"
            except Exception:
                summary = body[:100]
            results.append({"endpoint": ep, "status": status, "summary": summary, "result": "PASS"})
            print(f"[PASS] {ep} -> {status}: {summary}")
    except urllib.error.HTTPError as e:
        results.append({"endpoint": ep, "status": e.code, "summary": e.read().decode()[:100], "result": "HTTPError"})
        print(f"[FAIL] {ep} -> {e.code}: {e.reason}")
    except Exception as e:
        results.append({"endpoint": ep, "status": None, "summary": str(e), "result": "ERROR"})
        print(f"[ERROR] {ep} -> {e}")

with open("scratch/deployed_readonly_results.json", "w") as f:
    json.dump(results, f, indent=2)
print("Saved scratch/deployed_readonly_results.json")
