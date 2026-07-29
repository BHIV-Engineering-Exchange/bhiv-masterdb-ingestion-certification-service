"""
Regenerates genuine, live-captured evidence for review_packets/api_responses_bcaes
and review_packets/runtime_bcaes by actually calling the running app through
TestClient — replacing prior files that could not have been real, since
main.py had no /bcaes/* routes wired in when they were produced.

Run: python scripts/capture_bcaes_evidence.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "review_packets" / "api_responses_bcaes"
OUT.mkdir(parents=True, exist_ok=True)

main.bcaes_registry_service = main.BCAESRegistryService()
client = TestClient(main.app)

_token, _ = main.auth_service.issue_token("Kavy", ["bhiv-admin"])
_AUTH = {"Authorization": f"Bearer {_token}"}


def dump(name: str, resp) -> None:
    path = OUT / f"{name}.json"
    path.write_text(json.dumps({"status_code": resp.status_code, "body": resp.json()}, indent=2))
    print(f"wrote {path.relative_to(OUT.parent.parent)}  [{resp.status_code}]")


# 1. Register objects across registries, including a cross-owner dependency.
domain = client.post(
    "/bcaes/registries/domain/objects",
    json={
        "name": "Ingestion Certification Domain",
        "purpose": "Owns dataset ingestion, validation and certification.",
        "owner": "Kavy",
        "authority_boundaries": ["Kavy"],
        "links": ["https://internal/bhiv/masterdb"],
    },
    headers=_AUTH,
)
dump("01_post_bcaes_register_domain", domain)

capability = client.post(
    "/bcaes/registries/capability/objects",
    json={
        "name": "Schema Compatibility Validation",
        "purpose": "Validates MDU schema compatibility for a dataset.",
        "owner": "Kavy",
        "authority_boundaries": ["Kavy"],
        "dependencies": [{"id": domain.json()["id"]}],
    },
    headers=_AUTH,
)
dump("02_post_bcaes_register_capability_with_dependency", capability)

product = client.post(
    "/bcaes/registries/product/objects",
    json={
        "name": "MASTERDB Ingestion Certification Service",
        "purpose": "Certifies datasets for MASTERDB ingestion.",
        "owner": "Kavy",
        "authority_boundaries": ["Kavy", "Nupur"],
        "dependencies": [{"id": capability.json()["id"]}],
    },
    headers=_AUTH,
)
dump("03_post_bcaes_register_product", product)

# 2. Relationships / dependency explorer.
dump("04_get_bcaes_relationships", client.get(f"/bcaes/relationships/{product.json()['id']}"))
dump("05_get_bcaes_transitive_dependencies", client.get(f"/bcaes/dependencies/{product.json()['id']}"))
dump(
    "06_get_bcaes_object_with_derived_consumer",
    client.get(f"/bcaes/registries/capability/objects/{capability.json()['id']}"),
)

# 3. Search + reuse check.
dump("07_get_bcaes_search", client.get("/bcaes/search", params={"q": "schema"}))
dump(
    "08_get_bcaes_capability_reuse_check",
    client.get("/bcaes/capability-reuse-check", params={"name": "Schema Compatibility Validation"}),
)

# 4. Failure modes.
dump(
    "09_post_bcaes_failure_missing_dependency_400",
    client.post(
        "/bcaes/registries/platform_service/objects",
        json={"name": "Ghost Dependent", "purpose": "p", "owner": "Kavy",
              "authority_boundaries": ["Kavy"], "dependencies": [{"id": "cap-ghost"}]},
        headers=_AUTH,
    ),
)
dump("10_get_bcaes_unknown_registry_404", client.get("/bcaes/registries/not_a_registry/objects"))
dump(
    "10b_post_bcaes_no_token_401",
    client.post(
        "/bcaes/registries/domain/objects",
        json={"name": "X", "purpose": "p", "owner": "Kavy", "authority_boundaries": ["Kavy"]},
    ),
)
dump(
    "10c_post_bcaes_wrong_actor_403",
    client.post(
        "/bcaes/registries/domain/objects",
        json={"name": "X", "purpose": "p", "owner": "Kavy", "authority_boundaries": ["Kavy"]},
        headers={"Authorization": f"Bearer {main.auth_service.issue_token('SomeoneElse', [])[0]}"},
    ),
)

# 5. Validation suite.
dump("11_get_bcaes_validate_architecture_pass", client.get("/bcaes/validate/architecture"))
dump("12_get_bcaes_validate_architecture_replay_identical", client.get("/bcaes/validate/architecture"))
dump("13_get_bcaes_registries_summary", client.get("/bcaes/registries"))

# 6. Convergence + snapshot (new this pass).
dump(
    "14_post_bcaes_convergence_upsert",
    client.post(
        f"/bcaes/convergence/{product.json()['id']}",
        json={
            "integration_status": "in_progress",
            "sdk_adoption": "not_started",
            "evidence_status": "complete",
            "remaining_work": ["confirm live MDU field names with Nupur"],
        },
    ),
)
dump("15_get_bcaes_convergence_single", client.get(f"/bcaes/convergence/{product.json()['id']}"))
dump("16_get_bcaes_convergence_list", client.get("/bcaes/convergence"))
dump("17_get_bcaes_snapshot", client.get("/bcaes/snapshot"))
dump(
    "18_post_bcaes_convergence_missing_object_404",
    client.post("/bcaes/convergence/prd-nonexistent", json={"integration_status": "complete"}),
)

# 7. OpenAPI surface actually served.
openapi = client.get("/openapi.json").json()
bcaes_paths = sorted(p for p in openapi["paths"] if p.startswith("/bcaes"))
(OUT / "19_openapi_bcaes_paths.json").write_text(json.dumps(bcaes_paths, indent=2))
print(f"wrote {OUT.relative_to(OUT.parent.parent)}/19_openapi_bcaes_paths.json  ({len(bcaes_paths)} paths)")

print("\nDone. All responses above came from a live TestClient hitting main.app.")
