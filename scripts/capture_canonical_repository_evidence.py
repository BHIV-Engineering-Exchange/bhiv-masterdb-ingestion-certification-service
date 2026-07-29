"""Live-captured evidence for the Canonical Document Repository, driven
through a real TestClient against the running app (same pattern as
scripts/capture_bcaes_evidence.py). Updated for real JWT auth + RBAC
enforcement (added 28-29 July 2026, see PRODUCTION_HARDENING.md)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "review_packets" / "api_responses_canonical_repository"
OUT.mkdir(parents=True, exist_ok=True)

main.canonical_repository_service = main.CanonicalRepositoryService()
client = TestClient(main.app)


def _auth(actor="Kavy", roles=None):
    roles = roles if roles is not None else ["ecosystem-reader", "bcaes-editor"]
    token, _ = main.auth_service.issue_token(actor, roles)
    return {"Authorization": f"Bearer {token}"}


def dump(name: str, resp) -> None:
    (OUT / f"{name}.json").write_text(json.dumps({"status_code": resp.status_code, "body": resp.json()}, indent=2))
    print(f"wrote {name}.json [{resp.status_code}]")


dump(
    "00_post_no_token_401",
    client.post(
        "/canonical-repository/documents",
        json={"category": "bcaes_vol_4", "title": "x", "owner": "Kavy"},
    ),
)

doc = client.post(
    "/canonical-repository/documents",
    json={"category": "bcaes_vol_4", "title": "BCAES Volume 4 - Master Product & Capability Registry", "owner": "Kavy"},
    headers=_auth(),
)
dump("01_post_register_placeholder_document", doc)
doc_id = doc.json()["id"]

dump("02_get_latest_shows_placeholder", client.get(f"/canonical-repository/documents/{doc_id}/latest", headers=_auth()))
dump("03_post_duplicate_category_409", client.post(
    "/canonical-repository/documents",
    json={"category": "bcaes_vol_4", "title": "dup", "owner": "x"},
    headers=_auth(),
))
dump("04_get_unknown_category_404", client.get("/canonical-repository/by-category/not_a_volume", headers=_auth()))
dump("05_post_publish_real_version", client.post(
    f"/canonical-repository/documents/{doc_id}/versions",
    json={"content": "Real BCAES Vol 4 content would go here.", "change_note": "centrally populated", "published_by": "TaskLead"},
    headers=_auth(actor="TaskLead"),
))
dump("06_get_version_history", client.get(f"/canonical-repository/documents/{doc_id}/versions", headers=_auth()))
dump("07_get_verify_chain_intact", client.get(f"/canonical-repository/documents/{doc_id}/verify", headers=_auth()))
dump("08_get_document_status_now_published", client.get(f"/canonical-repository/documents/{doc_id}", headers=_auth()))
dump("09_get_list_all_documents", client.get("/canonical-repository/documents", headers=_auth()))
dump(
    "10_get_read_without_read_role_403",
    client.get(f"/canonical-repository/documents/{doc_id}", headers=_auth(actor="Outsider", roles=["irrelevant-role"])),
)
dump(
    "11_post_publish_without_write_role_403",
    client.post(
        f"/canonical-repository/documents/{doc_id}/versions",
        json={"content": "c", "change_note": "n", "published_by": "x"},
        headers=_auth(actor="Outsider", roles=["ecosystem-reader"]),
    ),
)
dump(
    "12_get_admin_role_bypasses_check",
    client.get(f"/canonical-repository/documents/{doc_id}", headers=_auth(actor="Ops", roles=["bhiv-admin"])),
)

openapi = client.get("/openapi.json").json()
paths = sorted(p for p in openapi["paths"] if p.startswith("/canonical-repository"))
(OUT / "13_openapi_paths.json").write_text(json.dumps(paths, indent=2))
print(f"wrote 13_openapi_paths.json ({len(paths)} paths)")
print("\nAll responses above came from a live TestClient hitting main.app.")
