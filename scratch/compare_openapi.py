import json
import sys
sys.path.insert(0, ".")
from main import app

with open("scratch/deployed_openapi.json", "r") as f:
    deployed = json.load(f)

local = app.openapi()
with open("scratch/local_openapi.json", "w") as f:
    json.dump(local, f, indent=2)

deployed_paths = set(deployed.get("paths", {}).keys())
local_paths = set(local.get("paths", {}).keys())

print(f"Deployed paths count: {len(deployed_paths)}")
print(f"Local paths count: {len(local_paths)}")

diff_deployed_only = deployed_paths - local_paths
diff_local_only = local_paths - deployed_paths

print(f"Paths in deployed but NOT in local ({len(diff_deployed_only)}):")
for p in sorted(diff_deployed_only):
    print("  +", p)

print(f"Paths in local but NOT in deployed ({len(diff_local_only)}):")
for p in sorted(diff_local_only):
    print("  -", p)

deployed_components = set(deployed.get("components", {}).get("schemas", {}).keys())
local_components = set(local.get("components", {}).get("schemas", {}).keys())

print(f"\nDeployed schemas count: {len(deployed_components)}")
print(f"Local schemas count: {len(local_components)}")
diff_schemas_dep = deployed_components - local_components
diff_schemas_loc = local_components - deployed_components
print(f"Schemas in deployed but NOT in local ({len(diff_schemas_dep)}):", diff_schemas_dep)
print(f"Schemas in local but NOT in deployed ({len(diff_schemas_loc)}):", diff_schemas_loc)
