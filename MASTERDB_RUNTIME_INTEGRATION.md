# MASTERDB Runtime Integration

**How MASTERDB's Phase 4/8 surfaces integrate with the live FastAPI runtime, adjacent services, and the BHIV ecosystem.**

---

## 1. FastAPI Wiring

### 1.1 Service Instantiation

At application startup (`main.py`, ~line 316), the following services are
instantiated in dependency order:

```python
# Phase 4 — Dataset Retrieval Service (Plug-and-Play Data Access)
dataset_retrieval_service = DatasetRetrievalService(
    registry=package_registry_service,
    knowledge_object_service=knowledge_object_service,
    retrieval_readiness_service=retrieval_readiness_service,
    mdu_adapter=mdu_contract_adapter,
)

# Phase 8 — Bucket Client (Evidence Preservation)
bucket_client = BucketClient()
```

All four constructor arguments are optional; the service defaults to fresh
instances if not provided. In `main.py` they are wired to the existing
singletons so the runtime shares state across endpoints.

### 1.2 Endpoint Registration

Endpoints are declared after existing route blocks (~line 720) to avoid
shadowing:

| Method | Path | Handler | Error Mapping |
|--------|------|---------|---------------|
| `GET` | `/datasets` | `list_datasets()` | — |
| `GET` | `/datasets/{dataset_id}` | `get_dataset()` | `404` on `PackageNotFoundError` |
| `GET` | `/datasets/{dataset_id}/schema` | `get_dataset_schema()` | — |
| `GET` | `/datasets/{dataset_id}/versions` | `get_dataset_versions()` | `404` on `PackageNotFoundError` |
| `GET` | `/datasets/{dataset_id}/provenance` | `get_dataset_provenance()` | `404` on `PackageNotFoundError` |
| `POST` | `/query` | `query_dataset()` | `404/400/403` |
| `POST` | `/export` | `export_dataset()` | `404/400/403` |
| `POST` | `/stream` | `stream_dataset()` | `404/400/403` |
| `POST` | `/reference` | `reference_dataset()` | `404/400/403` |
| `POST` | `/evidence/{evidence_id}` | `store_evidence()` | `503` on `BucketUnavailableError` |
| `GET` | `/evidence/{evidence_id}` | `get_evidence()` | `503` on `BucketUnavailableError` |
| `POST` | `/provenance/{dataset_id}` | `store_provenance()` | `503` on `BucketUnavailableError` |
| `GET` | `/provenance/{dataset_id}` | `get_provenance()` | `503` on `BucketUnavailableError` |
| `GET` | `/bucket/status` | `bucket_status()` | — |

### 1.3 Import Resolution

The following imports were added to `main.py`:

```python
from services.dataset_retrieval_service import (
    DatasetAccessDeniedError,
    DatasetNotRetrievableError,
    DatasetRetrievalService,
)
from services.bucket_client import BucketClient, BucketUnavailableError
from security.middleware import ReplayMitigationTable, RS256JWTVerifier, SecurityMiddleware
from services.crypto_audit_emitter import CryptoAuditEmitter
```

No duplicate imports remain after the cleanup.

---

## 2. Service Interactions

### 2.1 Dataset Retrieval Service -> Registry

- `list_datasets()` calls `registry.list_all()` (newly added method) and maps each `KnowledgePackage` to a summary dict.
- `get_dataset()` filters the full list by `dataset_id`; this preserves consistency even when multiple versions share the same `dataset_id`.

### 2.2 Dataset Retrieval Service -> Retrieval Readiness

- `_controlled_access()` calls `retrieval_readiness_service.assess(package_id)`.
- If the returned evidence status is `NOT_RETRIEVABLE` and the operation is not `reference`, a `DatasetNotRetrievableError` is raised.
- This ensures that only certified/verified datasets are accessible for query/export/stream, while `reference` is always permitted (subject to access policy).

### 2.3 Dataset Retrieval Service -> MDU Adapter

- `get_dataset_schema()` attempts `mdu_adapter.fetch_schema_contract(dataset_id)`.
- On any exception, it falls back to the registry-declared `schema_version`.
- `get_dataset_provenance()` attempts `mdu_adapter.fetch_provenance_contract(dataset_id)`; if unavailable, it returns MASTERDB's own lineage with `mdu_source: "unavailable"`.

### 2.4 Bucket Client -> Environment

- `PRAVAH_BHIV_BUCKET` sets the base URL.
- `BUCKET_API_KEY` sets the `X-API-Key` header.
- Absence of either results in `is_configured() == False` and HTTP 503 at the endpoint layer.

---

## 3. Runtime Discovery

The `/runtime/discovery` endpoint (Phase 3) advertises the new Phase 4/8
capabilities:

```json
{
  "capabilities": [
    "dataset_discovery",
    "schema_resolution",
    "provenance_aggregation",
    "governed_query",
    "governed_export",
    "governed_stream",
    "dataset_reference",
    "evidence_preservation",
    "provenance_preservation"
  ]
}
```

---

## 4. Deployment Checklist

- [ ] `PRAVAH_BHIV_BUCKET` and `BUCKET_API_KEY` are set in production.
- [ ] `PRAVAH_MASTERDB_API` points to the public ingress.
- [ ] MDU adapter environment (`PRAVAH_MDU_BASE_URL`, `MDU_API_KEY`) is configured if live MDU consumption is desired.
- [ ] Rate-limiting middleware is applied to `/query`, `/export`, `/stream` to prevent abuse.
- [ ] Logs are shipped from `masterdb` logger for `dataset_access_granted` and `dataset_access_denied` events.

---

## 5. Operational Runbook

### 5.1 Adding a New Dataset

1. `POST /packages/register` — create the package.
2. `POST /packages/{package_id}/promote` — advance through lifecycle.
3. `GET /datasets/{dataset_id}` — verify discovery.
4. `POST /query` or `/export` — verify governed access.

### 5.2 Investigating Access Denials

1. Check `retrieval_status` in the error detail.
2. If `NOT_RETRIEVABLE`, inspect `GET /datasets/{dataset_id}/provenance` for lineage gaps.
3. If `PARTIALLY_RETRIEVABLE`, check `allowed_operations` in the access policy.
4. Look for `dataset_access_granted` or `dataset_access_denied` logs.

### 5.3 Bucket Outage

1. `GET /bucket/status` returns `configured: false`.
2. All `/evidence/*` and `/provenance/*` calls return HTTP 503.
3. MASTERDB continues to serve dataset discovery and access; only persistence is paused.
