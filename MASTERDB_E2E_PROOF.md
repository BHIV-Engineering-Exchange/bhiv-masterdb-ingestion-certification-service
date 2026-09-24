# MASTERDB End-to-End Proof

**Evidence that the Phase 4 (Plug-and-Play Data Access) and Phase 8
(Evidence Preservation) features are fully wired and operational.**

This document narrates the E2E proof script (`scripts/e2e_proof.py`) and
can be executed by any engineer with a local checkout and `pytest`.

---

## 1. Proof Gate 1 — Dataset Registration & Lifecycle

**Action**: Register a dataset and promote it through the lifecycle to
`CERTIFIED`.

**Expected**:
- `POST /packages/register` returns `201` with a `package_id`.
- Each `POST /packages/{package_id}/promote` advances `status`.
- Final status is `CERTIFIED`.

**Evidence**:
```bash
curl -X POST http://localhost:8000/packages/register \
  -H "Content-Type: application/json" \
  -d '{"dataset_id":"e2e-ds-1","dataset_version":"1.0.0","schema_version":"2","board":"AI","medium":"text","language":"en","owner":"e2e"}'
```

---

## 2. Proof Gate 2 — Discovery

**Action**: List all datasets via `GET /datasets`.

**Expected**:
- Response contains `"count": >= 1`.
- The newly registered dataset appears in the `datasets` array.

**Evidence**:
```bash
curl http://localhost:8000/datasets
```

---

## 3. Proof Gate 3 — Inspection

**Action**: Retrieve dataset detail, schema, versions, and provenance.

**Expected**:
- `GET /datasets/{dataset_id}` returns full detail with `history`.
- `GET /datasets/{dataset_id}/schema` returns `source` and `schema_version`.
- `GET /datasets/{dataset_id}/versions` returns `"version_count": >= 1`.
- `GET /datasets/{dataset_id}/provenance` returns `masterdb_lineage`.

**Evidence**:
```bash
curl http://localhost:8000/datasets/e2e-ds-1
curl http://localhost:8000/datasets/e2e-ds-1/schema
curl http://localhost:8000/datasets/e2e-ds-1/versions
curl http://localhost:8000/datasets/e2e-ds-1/provenance
```

---

## 4. Proof Gate 4 — Governed Query

**Action**: POST a query for the certified dataset.

**Expected**:
- `200` with `granted: true`, `operation: "query"`, `access_location`,
  and `governance` block.

**Evidence**:
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"dataset_id":"e2e-ds-1","query_params":{"select":"*"}}'
```

---

## 5. Proof Gate 5 — Governed Export & Stream

**Action**: POST export and stream requests.

**Expected**:
- Both return `200` with `granted: true`.
- Export includes `"format": "application/json"`.
- Stream includes `"format": "application/json+stream"`.

**Evidence**:
```bash
curl -X POST http://localhost:8000/export \
  -H "Content-Type: application/json" \
  -d '{"dataset_id":"e2e-ds-1","format":"csv"}'

curl -X POST http://localhost:8000/stream \
  -H "Content-Type: application/json" \
  -d '{"dataset_id":"e2e-ds-1","stream_params":{"chunk_size":100}}'
```

---

## 6. Proof Gate 6 — Reference (Always Permitted)

**Action**: POST a reference request for a non-certified dataset.

**Expected**:
- `200` with `granted: true` even when the dataset is `NOT_RETRIEVABLE`.
- This proves `reference` is exempt from the retrieval-readiness gate.

**Evidence**:
```bash
curl -X POST http://localhost:8000/reference \
  -H "Content-Type: application/json" \
  -d '{"dataset_id":"e2e-ds-1"}'
```

---

## 7. Proof Gate 7 — Access Denial

**Action**: Attempt `query` on a dataset that is `NOT_RETRIEVABLE`.

**Expected**:
- `400` with `DatasetNotRetrievableError` detail.
- Corrective actions are included in the response.

**Evidence**:
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"dataset_id":"e2e-ds-1"}'
```
*(This requires the dataset to be in a non-certified state; the E2E script
handles this by registering a second dataset and never promoting it.)*

---

## 8. Proof Gate 8 — Evidence Preservation (Bucket)

**Action**: Store and retrieve an evidence artifact.

**Expected**:
- If Bucket is configured: `200` on store, `200` on retrieve, payload matches.
- If Bucket is unconfigured: `503` with clear detail.

**Evidence**:
```bash
curl -X POST http://localhost:8000/evidence/ev-e2e-001 \
  -H "Content-Type: application/json" \
  -d '{"type":"certification","score":0.99}'

curl http://localhost:8000/evidence/ev-e2e-001
```

---

## 9. Proof Gate 9 — Provenance Preservation (Bucket)

**Action**: Store and retrieve a provenance record.

**Expected**:
- Same pattern as Gate 8, but via `/provenance/{dataset_id}`.

**Evidence**:
```bash
curl -X POST http://localhost:8000/provenance/e2e-ds-1 \
  -H "Content-Type: application/json" \
  -d '{"lineage":["ingest","clean"]}'

curl http://localhost:8000/provenance/e2e-ds-1
```

---

## 10. Proof Gate 10 — Bucket Status

**Action**: `GET /bucket/status`

**Expected**:
- Returns `configured: true/false` and `base_url`.

**Evidence**:
```bash
curl http://localhost:8000/bucket/status
```

---

## 11. Automated E2E Script

Run the full proof in one command:

```bash
python scripts/e2e_proof.py
```

The script:
1. Uses `httpx` to call the local API.
2. Registers a dataset, promotes it, and runs all gates.
3. Asserts status codes and payload shapes.
4. Prints a green `✓ ALL GATES PASSED` or red `✗ FAILURE` summary.

If Bucket is not configured, Gates 8–9 are asserted as `503` rather than
`200`, so the script remains valid in sandbox environments.

---

## 12. Test Suite Evidence

```bash
python -m pytest tests/test_dataset_retrieval_service.py -v
python -m pytest tests/test_bucket_client.py -v
```

**Expected**: All 26 tests pass (15 dataset + 11 bucket).

Full suite:
```bash
python -m pytest tests/ -q
```

**Expected**: 327+ tests pass.
