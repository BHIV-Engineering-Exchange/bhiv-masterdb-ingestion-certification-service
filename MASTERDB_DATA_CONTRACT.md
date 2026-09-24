# MASTERDB Data Contract

**Phase 4 & Phase 8 — Interfaces between MASTERDB, MDU, Bucket, and BHIV consumers.**

This document defines the data contracts (schemas, payloads, and versioning
rules) that govern how MASTERDB exchanges information with its adjacent
systems: the MDU canonical layer and the Bucket evidence layer.

---

## 1. MASTERDB ↔ MDU Contract

### 1.1 Schema Contract

**MASTERDB request** (via `MDUContractAdapter.fetch_schema_contract(dataset_id)`):

- `dataset_id`: string, canonical identifier shared across BHIV.

**MDU response** (when live):

```json
{
  "schema_id": "schema-xxx",
  "dataset_id": "ds-1",
  "version": "2.0.0",
  "fields": [
    {"name": "id", "type": "string", "nullable": false},
    {"name": "value", "type": "float", "nullable": true}
  ],
  "constraints": {...},
  "updated_at": "2026-09-24T12:00:00Z"
}
```

**MASTERDB fallback** (when MDU unreachable):

```json
{
  "source": "registry-declared",
  "dataset_id": "ds-1",
  "schema_version": "2",
  "note": "MDU schema unavailable; returning registry-declared version only."
}
```

### 1.2 Provenance Contract

**MASTERDB request** (via `MDUContractAdapter.fetch_provenance_contract(dataset_id)`):

- `dataset_id`: string.

**MDU response** (when live):

```json
{
  "provenance_id": "prov-xxx",
  "dataset_id": "ds-1",
  "lineage": [
    {"step": "ingest", "source": "s3://bucket/raw", "timestamp": "..."},
    {"step": "clean", "source": "s3://bucket/clean", "timestamp": "..."}
  ],
  "verification_hash": "sha256:..."
}
```

**MASTERDB fallback** (when MDU unreachable):

MASTERDB returns its own `KnowledgeObjectService.lineage()` as
`masterdb_lineage`, with `mdu_provenance: []` and `mdu_source: "unavailable"`.

### 1.3 Version Compatibility Contract

MASTERDB delegates version-compatibility negotiation to MDU:

- `POST /version-compatibility` accepts `dataset_id`, `consumer_version`, `producer_version`.
- MDU returns `compatible`, `consumer_schema`, `producer_schema`, and `negotiation_id`.
- MASTERDB proxies this directly when the adapter client is configured.

---

## 2. MASTERDB ↔ Bucket Contract

### 2.1 Evidence Artifact

**MASTERDB → Bucket** (`POST /evidence`):

```json
{
  "evidence_id": "ev-2026-09-24-cert-xxx",
  "type": "certification|retrieval|audit",
  "dataset_id": "ds-1",
  "package_id": "pkg-xxx",
  "timestamp": "2026-09-24T19:00:00Z",
  "payload": {
    "status": "CERTIFIED",
    "rules": [...],
    "score": 0.98
  },
  "signature": "sha256:..."
}
```

**Bucket → MASTERDB** (`GET /evidence/{evidence_id}`):

- Returns the stored artifact verbatim, or `404` if absent.

### 2.2 Provenance Record

**MASTERDB → Bucket** (`POST /provenance`):

```json
{
  "dataset_id": "ds-1",
  "package_id": "pkg-xxx",
  "masterdb_lineage": [...],
  "mdu_provenance": [...],
  "merged_at": "2026-09-24T19:00:00Z"
}
```

**Bucket → MASTERDB** (`GET /provenance/{dataset_id}`):

- Returns the stored provenance record, or `404` if absent.

### 2.3 Failure Contract

If Bucket is unreachable or unconfigured, `BucketClient` raises
`BucketUnavailableError`, which `main.py` translates to:

```json
{
  "detail": "Bucket client is not configured (PRAVAH_BHIV_BUCKET missing)."
}
```

with HTTP status `503`.

---

## 3. MASTERDB Internal Data Contracts

### 3.1 Dataset Summary (Discovery)

```json
{
  "dataset_id": "ds-1",
  "package_id": "pkg-xxx",
  "dataset_version": "1.0.0",
  "schema_version": "2",
  "board": "AI",
  "medium": "text",
  "status": "CERTIFIED",
  "owner": "kavy",
  "created_at": "2026-09-24T10:00:00Z"
}
```

### 3.2 Dataset Detail (Inspection)

```json
{
  "dataset_id": "ds-1",
  "package_id": "pkg-xxx",
  "dataset_version": "1.0.0",
  "schema_version": "2",
  "board": "AI",
  "medium": "text",
  "language": "en",
  "owner": "kavy",
  "status": "CERTIFIED",
  "created_at": "...",
  "updated_at": "...",
  "history": [...],
  "knowledge_object": {...},
  "retrieval_evidence": {...}
}
```

### 3.3 Access Grant (Operation)

See `MASTERDB_CENTRAL_DATA_PLATFORM_SPEC.md` §3.4 for the canonical grant
structure. Every grant carries:

- `granted: true`
- `retrieval_status`
- `access_policy`
- `governance` (owner, classification, sensitivity, allowed_consumers, intended_use)
- `traceability` (params, evidence_id)

---

## 4. Versioning & Compatibility Rules

1. **Schema versions** are declared at registration (`schema_version`) and
   verified against MDU when the adapter is live.
2. **Dataset versions** are monotonically increasing by registration time;
   `GET /datasets/{dataset_id}/versions` sorts ascending.
3. **API contract**: All Phase 4/8 endpoints are version-agnostic in path;
   backward-compatible evolution is achieved by adding optional fields to
   request/response models, never removing existing ones.
4. **Bucket contract**: Evidence and provenance payloads are treated as
   opaque JSON blobs by Bucket; MASTERDB owns their schema.

---

## 5. Request / Response Models

The following Pydantic models were added to `models.py` for Phase 4 endpoints:

| Model | Fields | Used By |
|-------|--------|---------|
| `QueryRequest` | `dataset_id: str`, `query_params: dict | None` | `POST /query` |
| `ExportRequest` | `dataset_id: str`, `format: str | None` | `POST /export` |
| `StreamRequest` | `dataset_id: str`, `stream_params: dict | None` | `POST /stream` |
| `ReferenceRequest` | `dataset_id: str` | `POST /reference` |

All fields are optional where noted; missing values default to `None`.
