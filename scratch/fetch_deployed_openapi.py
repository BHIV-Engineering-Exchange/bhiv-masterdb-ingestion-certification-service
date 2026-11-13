import json
import urllib.request

url = "https://bhiv-masterdb-ingestion-certification.onrender.com/openapi.json"
req = urllib.request.Request(url, headers={"User-Agent": "Antigravity/1.0"})
with urllib.request.urlopen(req, timeout=30) as resp:
    data = json.loads(resp.read().decode())
    print("Deployed Title:", data.get("info", {}).get("title"))
    print("Deployed Version:", data.get("info", {}).get("version"))
    print("Deployed Paths Count:", len(data.get("paths", {})))
    with open("scratch/deployed_openapi.json", "w") as f:
        json.dump(data, f, indent=2)
print("Saved scratch/deployed_openapi.json")
