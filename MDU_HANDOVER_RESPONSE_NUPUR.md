# MASTERDB–MDU Provenance and Lineage Handover Response

**To:** Nupur Gavane (MDU Semantic Authority)  
**Cc:** Platform Supervisor & Integration Engineering Team  
**From:** Antigravity Integration Engineering Owner  
**Date:** 2026-10-29  
**Repository:** `Kavychangela/masterdb-ingestion-certification-service`  
**Git Branch:** `main` (Head Commit `3a8bd18` with clean working-tree integration)  
**Authoritative MDU Target:** `https://bhiv-mdu-api.onrender.com` (Render live instance; VM migration pending)  

---

## Executive Summary & Joint Evidential Boundary

This response provides exact, evidence-backed answers to the five queries and operational items raised in your 29 October 2026 communication and `MDU_PROVENANCE_LINEAGE_CONTRACT.md` (Sections 9–14).

All findings are classified across strict evidential boundaries:
1. **[LOCAL-VERIFIED]:** Verified through automated tests and local source code inspection in MASTERDB.
2. **[LIVE-READ-VERIFIED]:** Verified against the authoritative live Render MDU service via HTTP 200 OK responses.
3. **[LIVE-WRITE-PENDING]:** Mutation contracts implemented and verified locally via mock suites; live remote writes intentionally held pending dedicated sandbox dataset assignment.
4. **[DEPLOYED-PENDING]:** Local workstation verification complete; staging/production container deployment verification pending.
5. **[REPORTED-UNVERIFIED]:** Reported by MASTERDB architecture but not yet acknowledged or verified by MDU.
6. **[DECISION-PENDING]:** Requires explicit semantic sign-off from Nupur Gavane or the supervisor.

Zero API keys, tokens, credentials, or Bearer headers appear in this document.

---

## 1. Investigation of HTTP 401 Authentication Failures

### 1.1 Facts Established by Direct Evidence
- **Target Host & Environment:** `https://bhiv-mdu-api.onrender.com` (Render cloud deployment). The requests did **not** target the company internal VM, as local environment configurations consistently point to the Render base URL.
- **Root Cause Established [LOCAL-VERIFIED]:** The initial local development environment `.env` file contained an unconfigured placeholder token (`mdu_dev_key`) rather than a valid provisioned secret.
- **Resolution & Key Owner Established [LIVE-READ-VERIFIED]:** Upon updating `.env` with the active provisioned key assigned to owner **Kavy**, all outbound requests succeeded immediately with **HTTP 200 OK**.
- **Role & Scope Confirmed [LIVE-READ-VERIFIED]:** Probing `/api/v1/audit/logs` returned **HTTP 403 Forbidden** with error body stating `"Your role: ApiKeyRole.CONTRIBUTOR"`. This conclusively proves that:
  1. The key is valid and authenticated by MDU's `ApiKeyAuth` middleware.
  2. The key belongs to the `CONTRIBUTOR` role (which permits reading datasets/provenance and submitting provenance/relationship writes, but restricts administrative audit log retrieval to `REGISTRY_ADMIN`).
- **Header Used [LOCAL-VERIFIED]:** Outbound client `MDUClient._build_headers()` passes credentials exclusively via `X-API-Key: <masked>` and propagates `X-Trace-Id`.

### 1.2 Distinguishing Established Facts from Unknown Historical Factors
- **Historical 12:17 IST Request Origin:** We cannot conclusively establish whether the HTTP 401 errors logged at 12:17 IST on Nupur's side originated from a developer's workstation, a staging container, or an automated pipeline.
- **Key Rotation Recommendation:** While the current key for owner Kavy functions as expected, any key previously shared in unencrypted communication channels should be scheduled for routine rotation through MDU administration after current integration testing completes.

### 1.3 Safe Live Read Verification Evidence [LIVE-READ-VERIFIED]
- **Timestamp:** 2026-10-29T16:21:20+05:30
- **Endpoint 1:** `GET /api/v1/discovery/summary` $\rightarrow$ **HTTP 200 OK** (8 datasets discovered: 4 VERIFIED, 3 TRUSTED, 1 PROVISIONAL).
- **Endpoint 2:** `GET /api/v1/datasets/canonical/BHIV-DS-MARITIME-AIS-LIVE-001` $\rightarrow$ **HTTP 200 OK** (UUID `6f84dede-43f4-488d-8bb4-c17f712d7e1a`).
- **Endpoint 3:** `GET /api/v1/datasets/6f84dede-43f4-488d-8bb4-c17f712d7e1a/provenance` $\rightarrow$ **HTTP 200 OK** (5 historical provenance events retrieved).
- **Endpoint 4:** `GET /api/v1/relationships/dataset/6f84dede-43f4-488d-8bb4-c17f712d7e1a` $\rightarrow$ **HTTP 200 OK** (Relationship edge to child `a51b7702-ec04-4e7d-94d3-35927464a069` retrieved).
- **Endpoint 5:** `GET /api/v1/discovery/provenance/validate/6f84dede-43f4-488d-8bb4-c17f712d7e1a` $\rightarrow$ **HTTP 200 OK** (`valid: true`, `is_valid: true`, `record_count: 5`, `tantra_ready: true`).

---

## 2. Technical Inventory & Mapping for the Five Lineage Fields

The table below details the actual types, current operational semantics, representative examples, and MDU alignment status for each of MASTERDB's five core lineage fields.

| Field Name | Actual Python & DB Type | Meaning in Current MASTERDB Implementation | Representative Code / Fixture Example | Where Created, Stored, Read, and Returned | Candidate MDU Field(s) | Alignment Status & Decision | Evidence (File & Test) |
|---|---|---|---|---|---|---|---|
| `package_id` | `str` / `VARCHAR(256)` | Internal immutable package version identifier. Links `KnowledgeObject`s to dataset version releases. | `pkg-d8c7fc9168e5` *(actual from capability registry fixtures)* | Created in `PackageRegistryService.register_package()`; stored in `registry_store/{pkg}.json` / SQL; returned in `/packages` and `/knowledge-objects`. | None (MASTERDB internal lifecycle entity). | **CONFIRMED INTERNAL [LOCAL-VERIFIED].** Preserved in MASTERDB. MDU operates at dataset granularity; `package_id` is passed as metadata if required. | `models.py:102`<br>`services/package_registry_service.py:64`<br>`tests/test_package_registry.py` |
| `source_reference` | `str` / `TEXT` | Physical URI or logical origin path of raw input data. Required to pass `LINEAGE_REGISTERED` readiness rule. | `"svacs-unified-core/ais_feed"` or `"s3://masterdb-lake/raw/ais.csv"` | Provided in `KnowledgeObjectCreateRequest`; stored in `knowledge_objects/{id}.json` / SQL; checked by `RetrievalReadinessService`. | `ProvenanceRecord.source_reference` (MDU event payload). | **CONFIRMED MATCH [LOCAL-VERIFIED].** Direct 1:1 mapping. When creating MDU provenance events, MASTERDB supplies this directly to MDU `source_reference`. | `models.py:163`<br>`services/retrieval_readiness_service.py:124`<br>`tests/test_knowledge_object_service.py` |
| `parent_package` | `Optional[str]` / `VARCHAR(256)` | Immediate upstream parent package identifier. Forms ancestor chains across derived packages. | `"pkg-80168df644f2"` *(actual from fixtures)* | Provided in `KnowledgeObjectCreateRequest`; validated against `PackageRegistryService`; stored in `knowledge_objects/{id}.json`. | `DatasetRelationship.parent_dataset_id` (UUID). | **LOGICAL MATCH VIA ADAPTER [LOCAL-VERIFIED].** MASTERDB resolves parent package's dataset ID to MDU UUID via `MDUContractAdapter._resolve_mdu_id()` before recording lineage edges. | `models.py:161`<br>`services/knowledge_object_service.py:56-66`<br>`tests/test_knowledge_object_service.py` |
| `lineage_reference` | `Optional[str]` / `TEXT` | External opaque lineage identifier or graph pointer. Unstructured reference string. | `"mdu-rel-7be14e3d6b0e"` *(synthetic placeholder example)* | Accepted in `KnowledgeObjectCreateRequest`; stored in `knowledge_objects/{id}.json`; returned in `/knowledge-objects/{id}`. | MDU Relationship Edge ID (`id` from `POST /api/v1/relationships/`). | **CONFIRMED MATCH [LOCAL-VERIFIED].** Stores MDU's created relationship UUID or provenance event ID to reference external lineage state. | `models.py:164`<br>`services/mdu_contract_adapter.py:69`<br>`tests/test_mdu_contract_adapter.py` |
| `derivation_path` | `List[str]` / `JSON` | Ordered array of transformation steps applied to produce the package. Included in SHA-256 `knowledge_hash`. | `["filter_geo_bounds", "normalize_timestamps", "deduplicate_mmsi"]` | Provided in `KnowledgeObjectCreateRequest`; stored in `knowledge_objects/{id}.json`; used in `knowledge_hash` calculation. | `ProvenanceRecord.transformation_reference` (dict/string). | **ADAPTED MATCH [LOCAL-VERIFIED].** MDU accepts a transformation reference string or structured context. Adapter serializes `derivation_path` steps into `transformation_reference`. | `models.py:165`<br>`services/knowledge_object_service.py:69, 177`<br>`tests/test_knowledge_object_service.py` |

---

## 3. Provenance Storage Architectural Decision

### 3.1 Current Implementation Behavior
- **On-Demand Query Architecture [LOCAL-VERIFIED]:** MASTERDB does **not** duplicate MDU's event log into its local relational database or file stores. When a caller requests dataset provenance via `GET /datasets/{dataset_id}/provenance` or `GET /knowledge-objects/{id}/lineage`, MASTERDB invokes `MDUContractAdapter.fetch_provenance_contract()`, dynamically retrieving the verified provenance trail from MDU and exposing it under the `mdu_provenance` response attribute.
- **Degraded Fallback [LOCAL-VERIFIED]:** When MDU is unreachable or unconfigured, MASTERDB falls back to internal `KnowledgeObject` lineage edges and records `"source": "placeholder"` with circuit-breaker telemetry.

### 3.2 Formal Recommendation & Storage Policy
1. **Preserve On-Demand Master of Record Architecture:** MDU is the enterprise authority for provenance event history. Persisting full duplicate copies of event sequences in MASTERDB introduces dual-master drift and synchronization risks.
2. **Identifier Persistence Proposal (Minimal & Compatible):**
   - MASTERDB currently stores `dataset_id` (canonical string like `BHIV-DS-MARITIME-AIS-LIVE-001`).
   - MDU identifies datasets internally via UUID (`6f84dede-43f4-488d-8bb4-c17f712d7e1a`) and provenance events via event UUIDs.
   - **Decision:** MASTERDB should persist the canonical `dataset_id` and cache the MDU UUID in memory. Storing the single latest `mdu_lineage_event_id` (UUID) on `KnowledgeObject` is backward-compatible and provides direct indexing into MDU audit logs without duplicating event logs.

---

## 4. Trace Continuity Implementation & Boundaries

### 4.1 Trace Architecture Standards [LOCAL-VERIFIED]
- **Format:** Strict 32-character lowercase hexadecimal string (`^[0-9a-f]{32}$`).
- **Generation & Normalization:** Implemented in `utils/trace.py`:
  - `generate_trace_id()`: Creates a fresh 32-hex ID (`uuid.uuid4().hex`).
  - `normalize_trace_id(val)`: Strips legacy prefixes (`trace-`), hyphens, whitespace, and validates hex structure.
- **End-to-End Propagation Flow:**
  $$\text{Upload Initiation (POST /upload)} \longrightarrow \text{UploadJob.trace\_id} \longrightarrow \text{IngestJob.trace\_id (POST /ingest)} \longrightarrow \text{Outbound X-Trace-Id Header} \longrightarrow \text{MDU Audit Log}$$
- **Verification of Propagation:**
  - `test_ingest_preserves_upload_trace_id`: Verifies that an ingestion job linked to an upload via `upload_id` preserves the exact upload trace ID without generating a new one.
  - `test_mdu_client_headers_and_trace_propagation`: Verifies outbound `httpx` calls attach `X-Trace-Id: <32-hex>`.
- **MDU Trace Capture Semantics [LIVE-READ-VERIFIED]:** In MDU OpenAPI v1, individual `ProvenanceRecord` and `DatasetRelationship` objects do not have a dedicated `trace_id` column. Instead, `trace_id` is captured and correlated exclusively within MDU's centralized `AuditLogResponse` (`/api/v1/audit/logs`) along with `api_key_owner`, `method`, `path`, and `status_code`.

---

## 5. Dataset Ingestion Idempotency Implementation

### 5.1 Remediation Completed [LOCAL-VERIFIED]
To resolve the duplicate ingestion job creation identified during audit:
1. **Schema & Model Updates (`database_targets/models.py`):**
   - Added `idempotency_key: Optional[str] = None` to `IngestRequest` and `IngestJob`.
   - Defined `IdempotencyConflictError` for key reuse detection.
2. **Service Synchronization & Store (`database_targets/service.py`):**
   - Integrated disk-backed `_idempotency_store` (`ArtifactStore`).
   - Implemented thread-safe synchronization using reentrant locking (`threading.RLock`).
   - Identical retries with the same `idempotency_key` return the existing `IngestJob` with status `PERSISTED`, bypassing duplicate target persistence.
   - Reusing an existing key with conflicting `dataset_id` or `target_database` raises `IdempotencyConflictError`.
3. **API Interface (`main.py`):**
   - `POST /ingest` accepts `X-Idempotency-Key` HTTP header and `idempotency_key` body field.
   - Catches `IdempotencyConflictError` and returns **HTTP 409 Conflict**.

### 5.2 Verification Evidence
- `test_ingest_idempotency_identical_retry`: Verified single persistence on repeated submission.
- `test_ingest_idempotency_concurrency`: 5 concurrent threads submitting the identical key return the exact same job ID.
- `test_ingest_idempotency_conflict_raises`: Confirmed HTTP 409 exception upon parameter mismatch.
- `test_ingest_idempotency_distinct_keys`: Verified distinct keys create independent jobs.

---

## 6. Bucket Storage & Operational Readiness

### 6.1 Status & Ownership
- **Owner:** External PRAVAH storage subsystem (`services/bucket_client.py`).
- **Configuration:** Gated by `PRAVAH_BHIV_BUCKET` environment variable.
- **Workstation Status:** Unconfigured (`configured: False`).
- **Operational Fallback [LOCAL-VERIFIED]:** MASTERDB handles unconfigured bucket gracefully: upload and ingestion pipelines continue without failure, logging an informational notice. Bucket evidence preservation is optional for local development and staging verification, but must be configured with authorized cloud credentials prior to production sign-off.

---

## 7. Review-Ready Index of Source Files and Tests

### 7.1 Source Files Responsible for MDU & Lineage Behaviors
- **MDU API Client:** `services/mdu_client.py` (`MDUClient.record_provenance`, `create_relationship`, `get_dataset_schema`, `get_provenance`, `get_relationships`, `_build_headers`).
- **MDU Contract Adapter:** `services/mdu_contract_adapter.py` (`MDUContractAdapter.record_provenance_event`, `create_dataset_relationship`, `_resolve_mdu_id`, `negotiate_schema_version`).
- **Lineage & Knowledge Objects:** `services/knowledge_object_service.py` (`KnowledgeObjectService.create_knowledge_object`, `lineage`, `_compute_hash`).
- **Trace Correlation:** `utils/trace.py` (`generate_trace_id`, `normalize_trace_id`, `is_valid_trace_id`).
- **Upload Lifecycle & Intake:** `upload/service.py` and `upload/models.py` (`UploadService.initiate_upload`, `UploadJob.trace_id`).
- **Target Ingestion & Idempotency:** `database_targets/service.py` and `database_targets/models.py` (`DatabaseRouterService.ingest`, `_execute_ingest`, `_idempotency_store`).
- **API Boundary & Error Translation:** `main.py` (Route handlers for `/ingest`, `/upload`, `/datasets`, and exception handlers).

### 7.2 Automated Test Suites & Executed Commands
All tests executed on Windows workstation with Python 3.14.6:

```bash
# Core MDU Provenance Integration & Idempotency Test Suite (14 tests)
pytest tests/test_mdu_provenance_integration.py -v
# Outcome: 14 passed in 8.96s

# Full Regression Across Related Modules (61 tests)
pytest tests/test_mdu_provenance_integration.py tests/test_mdu_contract_adapter.py tests/test_upload_service.py tests/test_database_router_service.py tests/test_database_targets_api.py -v
# Outcome: 61 passed in 42.52s (0 failures, 0 errors)
```

**Exact Passing Tests in `tests/test_mdu_provenance_integration.py`:**
1. `test_trace_id_utilities`: Validates 32-hex generation and normalization.
2. `test_mdu_client_unconfigured`: Verifies graceful failure when MDU base URL is missing.
3. `test_mdu_client_headers_and_trace_propagation`: Verifies `X-API-Key` and `X-Trace-Id` headers.
4. `test_mdu_client_post_provenance`: Verifies payload format and response parsing for `POST /provenance`.
5. `test_mdu_client_create_relationship_and_read`: Verifies payload format for `POST /relationships/`.
6. `test_mdu_client_auth_failure_sanitization`: Verifies secrets are never leaked in 401 exceptions.
7. `test_mdu_client_forbidden_sanitization`: Verifies error redaction on 403 responses.
8. `test_adapter_record_provenance_event_resolves_id`: Verifies canonical-to-UUID resolution during provenance write.
9. `test_adapter_create_dataset_relationship_resolves_ids`: Verifies parent and child canonical-to-UUID resolution.
10. `test_ingest_preserves_upload_trace_id`: Verifies end-to-end trace ID continuity from upload to ingestion.
11. `test_ingest_idempotency_identical_retry`: Verifies duplicate suppression for repeated identical ingest calls.
12. `test_ingest_idempotency_conflict_raises`: Verifies HTTP 409 on parameter mismatch with reused key.
13. `test_ingest_idempotency_distinct_keys`: Verifies distinct keys create distinct jobs.
14. `test_ingest_idempotency_concurrency`: Verifies thread safety under concurrent burst submissions.

---

## 8. Remaining External Approvals & Live Staging Execution Plan

Only two external approvals remain before production sign-off:

1. **Dedicated Staging Dataset Identifier Assignment:**
   - **Authority:** Nupur Gavane (MDU Semantic Authority) or MDU Registry Admin.
   - **Action Needed:** Designate a dedicated sandbox dataset (e.g., `BHIV-DS-TEST-INGEST-001`) in MDU.
   - **Reason:** Production dataset `BHIV-DS-MARITIME-AIS-LIVE-001` must not be mutated with synthetic test events.
2. **Execution of Live Staging Verification Protocol:**
   - As soon as the staging dataset ID is provided, the automated test harness will execute:
     1. `GET /api/v1/datasets/{staging_id}/provenance` (capture baseline).
     2. `POST /api/v1/datasets/{staging_id}/provenance` (write event with trace ID).
     3. Verify HTTP 201 response and returned event UUID.
     4. `GET /api/v1/datasets/{staging_id}/provenance` (verify event presence).
     5. `GET /api/v1/discovery/provenance/validate/{staging_id}` (verify graph validity).

---

## 9. Final Handover Verdict

$$\mathbf{READY\ FOR\ STAGING\ TEST}$$

The MASTERDB codebase has completed all contract alignment, trace unification, client/adapter mutation implementations, error sanitization, and ingestion idempotency remediations. All 61 automated tests pass. Live read-only connectivity against Render MDU is verified. Final production sign-off is held strictly at the staging live-write boundary pending sandbox dataset assignment.
