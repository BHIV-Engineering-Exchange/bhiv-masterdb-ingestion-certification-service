# MASTERDB Central Data Platform Convergence Specification

**Phase 4 — Plug-and-Play Data Access & Phase 8 — Evidence Preservation.**

This document defines the completed convergence of MASTERDB into BHIV's
Central Data Platform. It is the source of truth for Phase 4 and Phase 8.

---

## 1. Goals & Non-Goals

### 1.1 Goals

- **Plug-and-Play Data Access**: Any BHIV consumer can discover, inspect, and access MASTERDB-certified datasets without product-specific integration code.
- **Governed Access**: Every data-access operation is gated by retrieval readiness evidence and a dataset-specific access policy.
- **Evidence Preservation**: Proofs of certification and runtime access can be deposited into Bucket for replay and audit.
- **Graceful Degradation**: When MDU or Bucket is unreachable, the platform falls back to registry-declared metadata.

### 1.2 Non-Goals

- **Not a data lake**: MASTERDB stores metadata and pointers, not raw dataset contents.
- **Not a schema authority**: Canonical schema semantics remain MDU's responsibility.
- **Not a rewrite**: All Task 1–3 surfaces remain untouched.

---

## 2. Architecture Overview

```
Consumer --> MASTERDB API --> Dataset Registry + Retrieval Readiness + Bucket Client
                |                          |
                +--> MDU Contract Adapter --+
```

### 2.1 Component Responsibilities

| Component | Responsibility |
|-----------|---------------|
| `DatasetRetrievalService` | Discovery, schema resolution, version listing, provenance aggregation, and governed access (query/export/stream/reference). |
| `BucketClient` | Evidence and provenance storage; degrades gracefully when unconfigured. |
| `PackageRegistryService` | Package identity and lifecycle; supports `list_all()` for discovery. |
| `RetrievalReadinessService` | Evidence-based gatekeeper for retrievability. |
| `MDUContractAdapter` | Live or placeholder bridge to MDU for schema, provenance, and version-compatibility. |

---

## 3. Dataset Access Model

### 3.1 Discovery

`GET /datasets` returns a summary of every registered dataset.

### 3.2 Inspection

| Endpoint | Purpose |
|----------|---------|
| `GET /datasets/{dataset_id}` | Full dataset detail with history, knowledge object, and retrieval evidence. |
| `GET /datasets/{dataset_id}/schema` | Schema contract (MDU-live if available; registry-declared fallback). |
| `GET /datasets/{dataset_id}/versions` | All versions of a dataset, sorted by creation time. |
| `GET /datasets/{dataset_id}/provenance` | MASTERDB lineage + MDU provenance (if available). |

### 3.3 Governed Access Operations

All operations pass through `_controlled_access()`, which enforces two gates:

1. **Retrieval Readiness Gate**: `NOT_RETRIEVABLE` blocks everything **except** `reference`.
2. **Access Policy Gate**: The resolved access policy must list the requested operation in `allowed_operations`.

| Endpoint | Operation | Open-Read | Restricted |
|----------|-----------|-----------|------------|
| `POST /query` | `query` | ✅ | ❌ |
| `POST /export` | `export` | ✅ | ❌ |
| `POST /stream` | `stream` | ✅ | ❌ |
| `POST /reference` | `reference` | ✅ | ✅ |

Open-Read applies when `package.status` is `CERTIFIED` or `RETRIEVAL_READY`.
Restricted applies to all other states.

### 3.4 Access Grant Structure

A successful access operation returns a JSON grant containing:
- `granted: true`
- `retrieval_status`
- `access_policy`
- `access_location`
- `governance` (owner, classification, sensitivity, allowed_consumers, intended_use)
- `traceability` (query_params, retrieval_evidence_id)

---

## 4. Evidence Preservation (Phase 8)

### 4.1 Bucket Integration Surface

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/evidence/{evidence_id}` | `POST` | Store a replayable evidence artifact. |
| `/evidence/{evidence_id}` | `GET` | Retrieve a stored evidence artifact. |
| `/provenance/{dataset_id}` | `POST` | Store a provenance record. |
| `/provenance/{dataset_id}` | `GET` | Retrieve stored provenance. |
| `/bucket/status` | `GET` | Client configuration / connectivity status. |

### 4.2 Graceful Degradation

If `PRAVAH_BHIV_BUCKET` is unset, `BucketClient.is_configured()` returns `False`. All Bucket endpoints return HTTP 503. No runtime crash occurs.

---

## 5. Error Contract

| Exception | HTTP Status | Trigger |
|-----------|-------------|---------|
| `PackageNotFoundError` | `404` | Unknown `dataset_id` or `package_id`. |
| `DatasetNotRetrievableError` | `400` | `NOT_RETRIEVABLE` and operation != `reference`. |
| `DatasetAccessDeniedError` | `403` | Operation not in `allowed_operations`. |
| `BucketUnavailableError` | `503` | Bucket unconfigured or unreachable. |

---

## 6. Test Coverage

- **15 tests** in `tests/test_dataset_retrieval_service.py`
- **11 tests** in `tests/test_bucket_client.py`

---

## 7. Runtime Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `PRAVAH_MASTERDB_API` | Base URL for access-location links. | `https://masterdb.bhiv.eco` |
| `PRAVAH_BHIV_BUCKET` | Bucket base URL. | *(none)* |
| `BUCKET_API_KEY` | API key for Bucket `X-API-Key` header. | *(none)* |

---

## 8. Proof Gates (E2E)

The E2E proof script (`scripts/e2e_proof.py`) demonstrates:

1. Register a dataset and promote it to `CERTIFIED`.
2. Discover it via `GET /datasets`.
3. Inspect schema, versions, and provenance.
4. Execute `query`, `export`, `stream`, and `reference`.
5. Store and retrieve evidence from Bucket (or confirm 503 when unconfigured).
6. Assert all gates return expected status codes and payloads.

See `MASTERDB_E2E_PROOF.md` for the full proof narrative.
