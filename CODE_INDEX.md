# CODE_INDEX.md — Phase 4 & Phase 8 (Central Data Platform Convergence)

**Task:** MASTERDB BHIV vNEXT KAVY TASK 1/3 — MasterDB Central Data Platform Convergence  
**Date:** 2026-09-25

---

## Directory Structure (key files only)

```
masterdb-ingestion-certification-service/
├── main.py                              # FastAPI app — all endpoints wired here
├── models.py                            # Pydantic models, PackageStatus, RetrievalStatus
├── requirements.txt                     # Strictly pinned (==) — no unpinned deps
│
├── api/
│   └── production.py
├── auth/
├── bcaes_registry/
├── canonical_repository/
├── config/
├── database_targets/
├── datasets/
├── engines/
├── evaluation_engine/
├── ingestion_jobs_store/
├── integrations/
├── knowledge_object_store/
├── middleware/
├── operational_sync/
├── profiling/
├── registry_store/
├── reports/
├── retrieval_evidence_store/
├── review_packets/
│   ├── REVIEW_PACKET.md
│   ├── CODE_INDEX.md
│   └── ...
├── scripts/
├── security/
├── services/
│   ├── artifact_store.py
│   ├── bucket_client.py                 # Phase 8: BucketClient (store/get evidence, store/get provenance)
│   ├── certification_service.py
│   ├── dataset_retrieval_service.py     # Phase 4: DatasetRetrievalService (list, get, query, export, stream, reference)
│   ├── knowledge_object_service.py      # Lineage for /provenance/{package_id}
│   ├── mdu_client.py
│   ├── mdu_contract_adapter.py          # MDU schema/provenance passthrough + fallback
│   ├── package_registry_service.py
│   ├── retrieval_readiness_service.py   # assess() gate for governed access
│   ├── runtime_discovery_service.py
│   └── ...
├── shared_data/
├── shared_store/
├── task_selector/
├── tests/
│   ├── conftest.py
│   ├── test_api.py
│   ├── test_bcaes_api.py
│   ├── test_central_data_platform_api.py  # NEW — Phase 4 & 8 integration tests
│   ├── test_dataset_retrieval_service.py   # 15 unit tests
│   ├── test_bucket_client.py               # 10 unit tests (get_evidence, store_provenance)
│   └── ...
└── utils/
```

---

## Changed Files (this task)

| File | Changes |
|------|---------|
| `main.py` | +4 inspection endpoints (`/datasets/{id}`, `/datasets/{id}/schema`, `/datasets/{id}/versions`, `/datasets/{id}/provenance`); +3 Phase 8 endpoints (`POST /evidence/{id}`, `GET /evidence/{id}`, `POST /provenance/{id}`); `DatasetNotRetrievableError` 404→400; `/runtime/identity` api_groups updated |
| `tests/test_central_data_platform_api.py` | +11 new tests for inspection and Phase 8 endpoints; `POST /evidence` test updated to use path param per spec §4.1 |
| `services/dataset_retrieval_service.py` | Pre-existing — powers all Phase 4 inspection and governed-access |
| `services/bucket_client.py` | Pre-existing — powers all Phase 8 evidence/provenance bucket operations |
| `REVIEW_PACKET.md` | This file — Phase 4/8 architectural proofs and self-audit |
| `CODE_INDEX.md` | This file — directory tree and changed files |

---

## New Files (this task)

| File | Purpose |
|------|---------|
| `tests/test_central_data_platform_api.py` | 23 integration tests for Phase 4 & 8 endpoints |
| `CODE_INDEX.md` | This file |

---

## Endpoint Inventory (Phase 4 + Phase 8)

### Phase 4 — Central Data Platform (Dataset Retrieval)

| Method | Path | Handler | Service Method | Error Mapping |
|--------|------|---------|----------------|---------------|
| GET | `/datasets` | `list_datasets` | `list_datasets()` | — |
| GET | `/datasets/{dataset_id}` | `get_dataset_detail` | `get_dataset()` | 404 |
| GET | `/datasets/{dataset_id}/schema` | `get_dataset_schema` | `get_dataset_schema()` | — |
| GET | `/datasets/{dataset_id}/versions` | `get_dataset_versions` | `get_dataset_versions()` | 404 |
| GET | `/datasets/{dataset_id}/provenance` | `get_dataset_provenance` | `get_dataset_provenance()` | 404 |
| POST | `/query` | `query_dataset` | `query()` | 404/400/403 |
| POST | `/export` | `export_dataset` | `export_dataset()` | 404/400/403 |
| POST | `/stream` | `stream_dataset` | `stream()` | 404/400/403 |
| POST | `/reference` | `reference_dataset` | `reference()` | 404/400 |

### Phase 8 — Evidence Preservation (Bucket)

| Method | Path | Handler | Service Method | Error Mapping |
|--------|------|---------|----------------|---------------|
| POST | `/evidence/{evidence_id}` | `store_evidence` | `store_evidence()` | 503 |
| GET | `/evidence/{evidence_id}` | `retrieve_evidence` | `get_evidence()` | 503 |
| POST | `/provenance/{dataset_id}` | `store_provenance` | `store_provenance()` | 503 |
| GET | `/provenance/{package_id}` | `get_provenance` | `lineage()` | 404 |
| GET | `/bucket/status` | `bucket_status` | `status()` | — |

### Runtime

| Method | Path | Handler |
|--------|------|---------|
| GET | `/runtime/identity` | `runtime_identity` |

---

## Dependency Pinning Verification

```
fastapi==0.115.8
uvicorn[standard]==0.34.0
pydantic==2.13.3
pydantic-core==2.46.3
requests==2.34.2
python-dotenv==1.2.2
cryptography==49.0.0
pytest==9.0.3
pytest-asyncio==0.24.0
httpx==0.28.1
numpy==2.5.0
openpyxl==3.1.5
pandas==3.0.3
PyJWT==2.13.0
SQLAlchemy==2.0.51
psycopg2-binary==2.9.12
starlette==0.45.3
```

✅ Zero unpinned `>=` dependencies. All versions are `==` pinned.