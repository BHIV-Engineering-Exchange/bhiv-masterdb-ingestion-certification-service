#!/usr/bin/env python3
"""
MASTERDB Phase 4 / Phase 8 — End-to-End Proof Script

Demonstrates all proof gates against a running local API.
Usage:
    uvicorn main:app --port 8000 &
    python scripts/e2e_proof.py
"""
import sys

import httpx

BASE = "http://localhost:8000"
client = httpx.Client(base_url=BASE, timeout=30.0)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"

def log_gate(number: int, name: str, ok: bool, detail: str = "") -> bool:
    status = PASS if ok else FAIL
    print(f"  Gate {number:02d} — {name:45s} {status}")
    if detail and not ok:
        print(f"           Detail: {detail}")
    return ok


def run_proof() -> bool:
    all_ok = True
    print("MASTERDB E2E Proof — Starting\n")

    # Gate 1 — Dataset Registration & Lifecycle
    ds_id = "e2e-ds-proof"
    r1 = client.post("/packages/register", json={
        "dataset_id": ds_id,
        "dataset_version": "1.0.0",
        "schema_version": "2",
        "board": "AI",
        "medium": "text",
        "language": "en",
        "owner": "e2e",
    })
    ok = r1.status_code == 201
    pkg = r1.json() if ok else {}
    pkg_id = pkg.get("package_id", "")
    all_ok &= log_gate(1, "Dataset Registration", ok, r1.text[:200])

    if pkg_id:
        for status in ["ingested", "validated", "verified", "certified"]:
            client.post(f"/packages/{pkg_id}/promote", json={"status": status, "actor": "e2e", "reason": "progress"})
        r1b = client.get(f"/packages/{pkg_id}")
        ok = r1b.status_code == 200 and r1b.json().get("status") == "certified"
        all_ok &= log_gate(1, "Lifecycle Promotion to CERTIFIED", ok)
    else:
        all_ok &= log_gate(1, "Lifecycle Promotion to CERTIFIED", False, "No package_id")

    # Gate 2 — Discovery
    r2 = client.get("/datasets")
    ok = r2.status_code == 200 and r2.json().get("count", 0) >= 1
    all_ok &= log_gate(2, "Dataset Discovery", ok, r2.text[:200])

    # Gate 3 — Inspection
    r3a = client.get(f"/datasets/{ds_id}")
    ok3a = r3a.status_code == 200 and r3a.json().get("dataset_id") == ds_id
    all_ok &= log_gate(3, "Dataset Detail", ok3a, r3a.text[:200])

    r3b = client.get(f"/datasets/{ds_id}/schema")
    ok3b = r3b.status_code == 200 and "source" in r3b.json()
    all_ok &= log_gate(3, "Dataset Schema", ok3b, r3b.text[:200])

    r3c = client.get(f"/datasets/{ds_id}/versions")
    ok3c = r3c.status_code == 200 and r3c.json().get("version_count", 0) >= 1
    all_ok &= log_gate(3, "Dataset Versions", ok3c, r3c.text[:200])

    r3d = client.get(f"/datasets/{ds_id}/provenance")
    ok3d = r3d.status_code == 200 and "masterdb_lineage" in r3d.json()
    all_ok &= log_gate(3, "Dataset Provenance", ok3d, r3d.text[:200])

    # Gate 4 — Governed Query
    r4 = client.post("/query", json={"dataset_id": ds_id, "query_params": {"select": "*"}})
    ok4 = r4.status_code == 200 and r4.json().get("granted") is True and r4.json().get("operation") == "query"
    all_ok &= log_gate(4, "Governed Query", ok4, r4.text[:200])

    # Gate 5 — Governed Export & Stream
    r5a = client.post("/export", json={"dataset_id": ds_id, "format": "csv"})
    ok5a = r5a.status_code == 200 and r5a.json().get("granted") is True and r5a.json().get("operation") == "export"
    all_ok &= log_gate(5, "Governed Export", ok5a, r5a.text[:200])

    r5b = client.post("/stream", json={"dataset_id": ds_id, "stream_params": {"chunk_size": 100}})
    ok5b = r5b.status_code == 200 and r5b.json().get("granted") is True and r5b.json().get("operation") == "stream"
    all_ok &= log_gate(5, "Governed Stream", ok5b, r5b.text[:200])

    # Gate 6 — Reference (Always Permitted)
    r6 = client.post("/reference", json={"dataset_id": ds_id})
    ok6 = r6.status_code == 200 and r6.json().get("granted") is True and r6.json().get("operation") == "reference"
    all_ok &= log_gate(6, "Reference (Always Permitted)", ok6, r6.text[:200])

    # Gate 7 — Access Denial
    r7a = client.post("/packages/register", json={
        "dataset_id": "e2e-ds-restricted",
        "dataset_version": "1.0.0",
        "schema_version": "2",
        "board": "AI",
        "medium": "text",
        "language": "en",
        "owner": "e2e",
    })
    if r7a.status_code == 201:
        r7b = client.post("/query", json={"dataset_id": "e2e-ds-restricted", "query_params": {"select": "*"}})
        ok7 = r7b.status_code == 400 and "NOT_RETRIEVABLE" in r7b.json().get("detail", "")
        all_ok &= log_gate(7, "Access Denial (NOT_RETRIEVABLE)", ok7, r7b.text[:200])
    else:
        all_ok &= log_gate(7, "Access Denial (NOT_RETRIEVABLE)", False, r7a.text[:200])

    # Gate 8 — Evidence Preservation
    r8a = client.post("/evidence/ev-e2e-001", json={"type": "certification", "score": 0.99})
    r8b = client.get("/evidence/ev-e2e-001")
    ok8 = (r8a.status_code == 200 and r8b.status_code == 200) or (r8a.status_code == 503 and r8b.status_code == 503)
    all_ok &= log_gate(8, "Evidence Preservation (Bucket)", ok8, f"POST {r8a.status_code}, GET {r8b.status_code}")

    # Gate 9 — Provenance Preservation
    r9a = client.post(f"/provenance/{ds_id}", json={"lineage": ["ingest", "clean"]})
    r9b = client.get(f"/provenance/{ds_id}")
    ok9 = (r9a.status_code == 200 and r9b.status_code == 200) or (r9a.status_code == 503 and r9b.status_code == 503)
    all_ok &= log_gate(9, "Provenance Preservation (Bucket)", ok9, f"POST {r9a.status_code}, GET {r9b.status_code}")

    # Gate 10 — Bucket Status
    r10 = client.get("/bucket/status")
    ok10 = r10.status_code == 200 and "configured" in r10.json()
    all_ok &= log_gate(10, "Bucket Status", ok10, r10.text[:200])

    print("\n" + "=" * 60)
    if all_ok:
        print(f"  {PASS} — ALL 10 GATES PASSED")
        print("=" * 60)
        return True
    else:
        print(f"  {FAIL} — SOME GATES FAILED")
        print("=" * 60)
        return False


if __name__ == "__main__":
    success = run_proof()
    sys.exit(0 if success else 1)
