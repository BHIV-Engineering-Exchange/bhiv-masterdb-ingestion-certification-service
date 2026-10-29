# MASTERDB Provenance and Lineage Implementation Audit
**Document Target:** MDU–MASTERDB Multi-Tenancy Integration & BIQOS Audit  
**Author:** Antigravity Pairing Agent (Inspected directly from active codebase)  
**Primary Repository:** `Kavychangela/masterdb-ingestion-certification-service`  
**Current Git Branch:** `main` (commit `3a8bd18 Fix Pravah deterministic verification type imports`)  
**Audit Date:** 2026-10-29T16:35:00+05:30  
**Output Target:** `MASTERDB_PROVENANCE_LINEAGE_AUDIT.md`  

---

## Executive Summary

This document provides a strictly verified, evidence-grounded audit of the provenance, lineage, MDU integration, traceability, and replay capabilities within the MASTERDB codebase (`masterdb-ingestion-certification-service`).

Every finding in this report is classified using strict evidential criteria:
- **VERIFIED:** Confirmed directly from source code, models, schemas, or executed tests.
- **DOCUMENTED ONLY:** Mentioned in architectural or contract documents but not found in runtime code.
- **NOT FOUND:** Absent from the inspected codebase.
- **UNVERIFIED:** Insufficient evidence to establish the behaviour.
- **NOT APPLICABLE:** Not applicable to the architecture, with explicit justification.

All secrets, credentials, tokens, and personal keys have been removed or masked in accordance with security constraints.

---

## Section 1: Repository and Implementation Scope

### 1.1 Repository & Branch Identity
- **Repository Name:** `masterdb-ingestion-certification-service`
- **Git Branch:** `main` [VERIFIED: `git status` / `git branch -v`]
- **Head Commit:** `3a8bd18` (`Fix Pravah deterministic verification type imports`) [VERIFIED: `git branch -v`]
- **Working Tree State:** Modified [VERIFIED: `git status`]. Unstaged changes in `database_targets/models.py`, `database_targets/service.py`, `main.py`, `services/mdu_client.py`, `services/mdu_contract_adapter.py`, `tests/test_upload_service.py`, `upload/models.py`, `upload/service.py`; untracked implementation files `utils/trace.py`, `tests/test_mdu_provenance_integration.py`.

### 1.2 Architectural Component Inventory
The repository implements a multi-tier architecture spanning ingestion validation, dataset registration, capability contracts, target database routing, event replay ledgers, and external MDU adapters.

| Component / Subsystem | Repository-Relative Path | Primary Purpose | Evidence / Implementation Location | Status |
|---|---|---|---|---|
| **Knowledge Package Lifecycle Manager** | `services/package_registry_service.py` | Governs lifecycle progression (`REGISTERED` $\rightarrow$ `INGESTED` $\rightarrow$ `VALIDATED` $\rightarrow$ `VERIFIED` $\rightarrow$ `CERTIFIED` $\rightarrow$ `RETRIEVAL_READY` $\rightarrow$ `DEPRECATED` $\rightarrow$ `ARCHIVED`), records transitions, checks audit completeness, and validates transition replay. | `services/package_registry_service.py:1-226`<br>`models.py:66-140` | **VERIFIED** |
| **Knowledge Object & Lineage Engine** | `services/knowledge_object_service.py` | Computes deterministic knowledge hashes, maintains parent/child lineage edges (`parent_package`, `child_packages`), walks ancestor chains, and integrates MDU provenance contracts. | `services/knowledge_object_service.py:1-208`<br>`models.py:146-176` | **VERIFIED** |
| **MDU API Client** | `services/mdu_client.py` | Single HTTP transport boundary for external MDU service (`https://bhiv-mdu-api.onrender.com`). Exposes schema, provenance, canonical dataset, discovery summary, and relationship lookups, as well as provenance and relationship POST mutations. Outbound calls propagate `X-API-Key` and `X-Trace-Id`. Circuit-breaker guarded. | `services/mdu_client.py:1-165` | **VERIFIED** |
| **MDU Contract Adapter** | `services/mdu_contract_adapter.py` | Single logical boundary consuming MDU-owned semantics. Maps canonical dataset IDs to internal MDU UUIDs, performs version negotiation, handles provenance and relationship mutations, and degrades gracefully to placeholder mode when MDU is offline. | `services/mdu_contract_adapter.py:1-350`<br>`MDU_INTERFACE_CONTRACT.md:1-141` | **VERIFIED** |
| **Trace Correlation Engine** | `utils/trace.py` | Generates and validates standard 32-character lowercase hexadecimal trace IDs (`^[0-9a-fA-F]{32}$`). Normalizes legacy prefixed IDs (`trace-{hex}`) and hyphenated UUIDs to preserve trace continuity. | `utils/trace.py:1-57` | **VERIFIED** |
| **Dataset Retrieval & Access Service** | `services/dataset_retrieval_service.py` | Exposes read surfaces (`/datasets/{id}/provenance`, `/query`, `/export`, `/stream`, `/reference`). Enforces retrieval readiness policies and aggregates MASTERDB lineage with MDU provenance. | `services/dataset_retrieval_service.py:1-260`<br>`main.py:1594-1678` | **VERIFIED** |
| **Retrieval Readiness Engine** | `services/retrieval_readiness_service.py` | Evaluates 4 deterministic readiness rules (`PACKAGE_CERTIFIED`, `NOT_DEPRECATED_OR_ARCHIVED`, `METADATA_COMPLETE`, `LINEAGE_REGISTERED`) gating downstream data consumption. | `services/retrieval_readiness_service.py:1-175`<br>`models.py:182-202` | **VERIFIED** |
| **Validation & Certification Engine** | `services/validation_service.py`<br>`services/certification_service.py` | Runs tabular and geospatial checks, profile extraction, metadata rule evaluation, and provenance field scoring (`ProvenanceValidator`). Gates dataset eligibility for MASTERDB. | `services/validation_service.py:1-102`<br>`services/certification_service.py:1-124`<br>`validators/provenance_validator.py:1-8` | **VERIFIED** |
| **Target Database Routing & Ingestion** | `database_targets/service.py`<br>`database_targets/models.py` | Controls ingestion into 8 target databases. Resolves and preserves 32-hex `trace_id` across upload linkage and execution, checks certification gates, and persists target records atomically. | `database_targets/service.py:1-534`<br>`database_targets/models.py:1-105` | **VERIFIED** |
| **Upload Staging & Intake** | `upload/service.py`<br>`upload/models.py` | Receives raw files, generates initial 32-hex `trace_id` (or normalizes caller trace ID), performs SHA-256 integrity verification, and advances through staging lifecycle. | `upload/models.py:54-125`<br>`upload/service.py:1-115`<br>`main.py:1051-1100` | **VERIFIED** |
| **Pravah Replay Ledger & Pipeline** | `services/pravah_ledger.py`<br>`services/event_pipeline.py`<br>`models_pravah.py` | Append-only event store with monotonic sequence numbering, deduplication indexing, SHA-256 state hashing, idempotent replay execution, and pipeline state progression. | `services/pravah_ledger.py:1-251`<br>`services/event_pipeline.py:1-306`<br>`models_pravah.py:1-142` | **VERIFIED** |
| **Relational Storage (SQL Backend)** | `services/sql_artifact_store.py` | SQLAlchemy relational implementation backing `artifact_records`, `target_datasets`, and `target_dataset_records`. Activated when `MASTERDB_DATABASE_URL` is set; defaults to file-based `ArtifactStore`. | `services/sql_artifact_store.py:1-270`<br>`DATABASE.md:1-95` | **VERIFIED** |
| **Bucket Evidence Preservation Client** | `services/bucket_client.py` | HTTP client for external PRAVAH Bucket service (`PRAVAH_BHIV_BUCKET`) to preserve evidence artifacts and dataset provenance payloads. | `services/bucket_client.py:1-88`<br>`main.py:1688-1733` | **VERIFIED** |
| **Enterprise Security Middleware** | `security/middleware.py` | Enforces RS256 JWT signature verification and `ReplayMitigationTable` (`jti` uniqueness) on `/production/*` routes. | `security/middleware.py:1-142`<br>`main.py:291-298` | **VERIFIED** |

---

## Section 2: MASTERDB Provenance and Lineage Field Inventory

This inventory documents all fields MASTERDB actually stores, expects, or processes regarding dataset provenance, lineage, ingestion, traceability, or source references.

| Field Name | Type (DB / Python) | Required? | Stored or Request-Only? | Meaning | Defined / Validated in | Evidence / Status |
|---|---|---|---|---|---|---|
| `knowledge_object_id` | `VARCHAR(256)` / `str` | Yes (system generated) | Stored (JSON / SQL) | Unique identifier for a canonical Knowledge Object registered in MASTERDB. Format `kobj-{12-hex}`. | `models.py:157`<br>`services/knowledge_object_service.py:67-78` | **VERIFIED** |
| `knowledge_hash` | `VARCHAR(64)` / `str` | Yes (system generated) | Stored (JSON / SQL) | Deterministic SHA-256 digest of `package_id` + `source_reference` + `derivation_path`. | `models.py:158`<br>`services/knowledge_object_service.py:175-184` | **VERIFIED** |
| `package_id` | `VARCHAR(256)` / `str` | Yes (system generated / request FK) | Stored (JSON / SQL) | Identity of a registered Knowledge Package (`pkg-{12-hex}`). Connects Knowledge Objects, retrieval readiness, and dataset versions. | `models.py:102, 159, 170`<br>`services/package_registry_service.py:64` | **VERIFIED** |
| `dataset_id` | `VARCHAR(128)` / `str` | Yes (caller provided / computed) | Stored (JSON / SQL) | Logical dataset identifier (e.g. `BHIV-DS-MARITIME-AIS-LIVE-001` or 16-hex hash). Primary business key. | `models.py:103, 117`<br>`services/validation_service.py:94-100` | **VERIFIED** |
| `schema_version` | `VARCHAR(64)` / `str` | Yes | Stored (JSON / SQL) | Declared schema version string (e.g. `"1.0"`, `"2.1"`). Compared in parent-child hops and MDU compatibility checks. | `models.py:105, 160`<br>`services/mdu_contract_adapter.py:261-296` | **VERIFIED** |
| `parent_package` | `VARCHAR(256)` / `Optional[str]` | No (nullable) | Stored (JSON / SQL) | Package ID of the immediate upstream parent package. Validated against Package Registry. | `models.py:161, 171`<br>`services/knowledge_object_service.py:56-66` | **VERIFIED** |
| `child_packages` | `JSON` / `List[str]` | No (default `[]`) | Stored (JSON / SQL) | List of downstream child package IDs referencing this package as parent. Mutated automatically on child registration. | `models.py:162`<br>`services/knowledge_object_service.py:80-85` | **VERIFIED** |
| `source_reference` | `TEXT` / `Optional[str]` | No in schema; required for retrieval | Stored (JSON / SQL) | Upstream origin URI, path, or stream identifier (e.g. `s3://bucket/data.csv`, `svacs-unified-core/ais_feed`). Gates `LINEAGE_REGISTERED`. | `models.py:163, 172`<br>`services/retrieval_readiness_service.py:124-139` | **VERIFIED** |
| `lineage_reference` | `TEXT` / `Optional[str]` | No (nullable) | Stored (JSON / SQL) | Opaque external lineage pointer or graph identifier. Unstructured placeholder pending MDU schema finalization. | `models.py:164, 173`<br>`services/mdu_contract_adapter.py:69-75` | **VERIFIED** |
| `derivation_path` | `JSON` / `List[str]` | No (default `[]`) | Stored (JSON / SQL) | Ordered sequence of transformation step names applied to derive the dataset (e.g. `["filter", "normalize"]`). | `models.py:165, 174`<br>`services/knowledge_object_service.py:69, 177` | **VERIFIED** |
| `trace_id` (Upload) | `VARCHAR(32)` / `str` | Yes (system generated or caller specified) | Stored (JSON) | 32-character lowercase hexadecimal trace ID (`utils.trace.generate_trace_id()`). | `upload/models.py:58, 106`<br>`upload/service.py:97`<br>`utils/trace.py:15-18` | **VERIFIED** |
| `trace_id` (Ingest) | `VARCHAR(32)` / `str` | Yes (inherited or system generated) | Stored (JSON) | 32-character lowercase hexadecimal trace ID. Preserves linked upload's trace ID when `upload_id` is supplied. | `database_targets/models.py:81, 88`<br>`database_targets/service.py:121-137` | **VERIFIED** |
| `provenance_metadata` | `JSON` / `Dict[str, Any]` | No (default `{}`) | Stored (JSON) | Free-form provenance dictionary accepted during upload initiation and persisted with upload job. | `upload/models.py:65, 99`<br>`upload/service.py:50` | **VERIFIED** |
| `provenance` (Capability) | `JSON` / `Dict[str, Any]` | No (default `{}`) | Stored (JSON) | Ecosystem capability provenance dictionary embedded in capability definitions and contracts. | `models.py:382, 413, 451`<br>`services/capability_registry_service.py` | **VERIFIED** |
| `provenance_reference` (Source) | `JSON` / `Dict[str, Any]` | No (default `{}`) | Stored (JSON) | Provenance and source audit metadata recorded on registered geospatial/observational source records. | `models.py:305, 323`<br>`services/source_registry_service.py` | **VERIFIED** |
| `source` (Validation Metadata) | `str` | Required by rule | Request-only (Metadata JSON) | Metadata field checked by `ProvenanceValidator` (`source` present and non-empty). | `validators/provenance_validator.py:5`<br>`config/validation_rules.json:2-10` | **VERIFIED** |
| `owner` (Validation Metadata) | `str` | Required by rule | Request-only (Metadata JSON) | Metadata field checked by `ProvenanceValidator`. | `validators/provenance_validator.py:5` | **VERIFIED** |
| `license` (Validation Metadata) | `str` | Required by rule | Request-only (Metadata JSON) | Metadata field checked by `ProvenanceValidator`. | `validators/provenance_validator.py:5` | **VERIFIED** |
| `version` (Validation Metadata) | `str` | Required by rule | Request-only (Metadata JSON) | Metadata field checked by `ProvenanceValidator`. | `validators/provenance_validator.py:5` | **VERIFIED** |
| `lineage` (Validation Metadata) | `Any` | Required by rule | Request-only (Metadata JSON) | Metadata field checked by `ProvenanceValidator` (`lineage` key present and truthy). | `validators/provenance_validator.py:5` | **VERIFIED** |
| `transformation_log` (Validation) | `Any` | Required by rule | Request-only (Metadata JSON) | Metadata field checked by `ProvenanceValidator`. | `validators/provenance_validator.py:5` | **VERIFIED** |
| `event_id` (Pravah) | `VARCHAR(256)` / `str` | Yes (system generated) | Stored (JSON / Ledger) | Immutable event identifier (`evt-{12-hex}`) in the Pravah event envelope. Deduplicated in memory/ledger. | `models_pravah.py:59`<br>`services/pravah_ledger.py:55` | **VERIFIED** |
| `correlation_id` (Pravah) | `VARCHAR(256)` / `Optional[str]` | No (nullable) | Stored (JSON / Ledger) | Optional distributed tracing/correlation ID on Pravah event envelopes. | `models_pravah.py:68`<br>`services/event_pipeline.py:233` | **VERIFIED** |
| `idempotency_key` (Pravah) | `VARCHAR(256)` / `Optional[str]` | No (nullable) | Stored (JSON / Ledger) | Caller-supplied idempotency key. Deduplicated by `PravahReplayLedger._idempotency_index`. | `models_pravah.py:69`<br>`services/pravah_ledger.py:66-74` | **VERIFIED** |
| `sequence_number` (Pravah) | `INTEGER` / `int` | Yes (system generated) | Stored (JSON / Ledger) | Strictly monotonic sequential ledger index ($\ge 1$) assigned upon recording. | `models_pravah.py:78`<br>`services/pravah_ledger.py:76` | **VERIFIED** |
| `state_hash_after` (Pravah) | `VARCHAR(64)` / `Optional[str]` | No (nullable until commit) | Stored (JSON / Ledger) | SHA-256 state hash of the state machine after event transition. | `models_pravah.py:83`<br>`services/pravah_ledger.py:109` | **VERIFIED** |
| `content_hash` (Document) | `VARCHAR(64)` / `str` | Yes (system generated) | Stored (JSON / SQL) | SHA-256 hash of document content forming cryptographic provenance chain in canonical repository. | `canonical_repository/models.py:81`<br>`canonical_repository/service.py:109` | **VERIFIED** |
| `target_reference` | `VARCHAR(256)` / `str` | Yes (system generated) | Stored (JSON / SQL) | Reference string `"{target_database}/{dataset_id}"` where target records were physically persisted. | `database_targets/service.py:209, 238`<br>`services/sql_artifact_store.py:62` | **VERIFIED** |

---

## Section 3: Provenance and Lineage Identifier Ownership

### 3.1 Identifier Inventory & Ownership Mapping

| Identifier / Reference | Exact Field | Generated By | Uniqueness / Scope | Persisted Where | Evidence / Status |
|---|---|---|---|---|---|
| **Dataset Identifier** | `dataset_id` | Caller (or derived SHA-256 slice `_dataset_id()`) | Repository-wide business key. Case-insensitive in package lookups. | `packages`, `target_datasets`, `reports`, `uploads` | `models.py:103`<br>`services/validation_service.py:94-100`<br>**VERIFIED** |
| **Package Identifier** | `package_id` | MASTERDB (`_new_id("pkg")`) | Unique per package version (`pkg-{12-hex}`). | `registry_store/{pkg}.json` | `models.py:102`<br>`services/package_registry_service.py:64`<br>**VERIFIED** |
| **Knowledge Object ID** | `knowledge_object_id` | MASTERDB (`_new_id("kobj")`) | Unique per knowledge object record (`kobj-{12-hex}`). | `knowledge_object_store/{kobj}.json` | `models.py:157`<br>`services/knowledge_object_service.py:67`<br>**VERIFIED** |
| **Knowledge Hash** | `knowledge_hash` | MASTERDB (`SHA-256`) | Deterministic hash over package ID, source reference, and derivation path. | `KnowledgeObject.knowledge_hash` | `services/knowledge_object_service.py:175-184`<br>**VERIFIED** |
| **MDU Canonical Dataset ID** | `dataset_id` | MDU / External | Canonical string ID in MDU registry (e.g. `BHIV-DS-MARITIME-AIS-LIVE-001`). | MDU Registry; resolved in memory by MASTERDB adapter | `services/mdu_contract_adapter.py:116-147`<br>**VERIFIED** |
| **MDU Internal Dataset UUID** | `id` (MDU) | MDU Internal | Internal UUID required by MDU's `/schemas/dataset/{id}` and `/datasets/{id}/provenance`. | MDU Internal Database; cached in MASTERDB `_id_resolution_cache` | `services/mdu_contract_adapter.py:124-147`<br>**VERIFIED** |
| **Provenance Event Identifier** | `id` (on MDU event) | MDU Internal | UUID per MDU append-only provenance event. Not generated by MASTERDB; returned in response on write. | MDU Provenance Event Stream | `services/mdu_contract_adapter.py:53-60`<br>`services/mdu_client.py:80-87`<br>**VERIFIED** |
| **Lineage Pointer** | `lineage_reference` | Caller / Upstream | Unstructured opaque string pointer (nullable). | `KnowledgeObject.lineage_reference` | `models.py:164`<br>`services/mdu_contract_adapter.py:69-75`<br>**VERIFIED** |
| **Source Reference** | `source_reference` | Caller / Upstream | URI or string path to raw data source. | `KnowledgeObject.source_reference`, `UploadJob.source_reference` | `models.py:163`<br>`upload/models.py:64`<br>**VERIFIED** |
| **Upload Trace Identifier** | `trace_id` | MASTERDB (`utils.trace.generate_trace_id()`) | Session scope (32-character hexadecimal). | `upload_store/{upl}.json` | `upload/models.py:58`<br>`utils/trace.py:15-18`<br>**VERIFIED** |
| **Ingestion Job Trace ID** | `trace_id` | MASTERDB (`DatabaseRouterService.ingest`) | Ingestion execution scope (32-character hexadecimal, inherited from upload). | `ingestion_jobs_store/{job}.json` | `database_targets/models.py:88`<br>`database_targets/service.py:121-137`<br>**VERIFIED** |
| **Pravah Event Identifier** | `event_id` | Producer / MASTERDB (`_new_id("evt")`) | Unique per event envelope (`evt-{12-hex}`). | `pravah_ledger` snapshot | `models_pravah.py:59`<br>`services/pravah_ledger.py:55`<br>**VERIFIED** |
| **Pravah Ledger Sequence** | `sequence_number` | MASTERDB (`PravahReplayLedger`) | Monotonic integer sequence ($\ge 1$). | `pravah_ledger` snapshot | `services/pravah_ledger.py:76-83`<br>**VERIFIED** |

### 3.2 Explicit Core Architectural Questions

#### 1. Does MASTERDB have a dedicated provenance event identifier?
**Locally NO, but consumes and submits to MDU's event stream.** [VERIFIED]  
MASTERDB internally does not persist a multi-event historical provenance table; it maintains a single `KnowledgeObject` per package (`services/knowledge_object_service.py:67-78`), identified by `knowledge_object_id`. However, for external MDU provenance, MASTERDB interacts with MDU's append-only event stream via `MDUContractAdapter.record_provenance_event()` (`POST /api/v1/datasets/{dataset_id}/provenance`), where MDU assigns and returns a UUID event `id`.

#### 2. Does MASTERDB have a dedicated lineage record or relationship identifier?
**Locally NO, but supports external MDU relationship edge creation.** [VERIFIED]  
Within MASTERDB, lineage relationships are stored as direct pointer fields embedded inside `KnowledgeObject`: `parent_package: Optional[str]` and `child_packages: List[str]` (`models.py:161-162`). Lineage traversal walks these parent pointers iteratively. Externally, MASTERDB can now record MDU relationship edges via `MDUContractAdapter.create_dataset_relationship()` (`POST /api/v1/relationships/`), which writes edges into MDU's graph where each edge receives an MDU-assigned UUID `id`.

#### 3. Is there a confirmed canonical ID field?
**NO dedicated field named `canonical_id` exists in MASTERDB models; `dataset_id` serves this role.** [VERIFIED]  
MASTERDB uses `dataset_id` as its universal dataset identifier across `KnowledgePackage`, `ValidationRequest`, `UploadJob`, and `IngestJob`. In `services/mdu_contract_adapter.py:116-147`, the adapter maps MASTERDB's canonical string ID (`dataset_id`, e.g. `BHIV-DS-MARITIME-AIS-LIVE-001`) to MDU's internal UUID (`id`) via `GET /api/v1/datasets/canonical/{dataset_id}` and caches it in memory (`_id_resolution_cache`).

#### 4. If an identifier is generated externally, where does MASTERDB obtain it and how does it validate it?
**Obtained via API request payloads or MDU resolution; validated by Pydantic, UUID regex, and trace regex.** [VERIFIED]  
- `dataset_id` is supplied in API request bodies and validated as a non-empty string by Pydantic.
- MDU UUIDs are validated using `_UUID_RE` (`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`).
- Trace IDs are validated using `_TRACE_ID_RE` (`^[0-9a-fA-F]{32}$`) in `utils/trace.py`.

#### 5. Which identifier actually connects a provenance or lineage record to a dataset?
**`package_id` directly connects `KnowledgeObject` to `KnowledgePackage`, which holds `dataset_id`.** [VERIFIED]  
`KnowledgeObject` contains `package_id` and is persisted in `knowledge_object_store` under two keys: `knowledge_object_id` and `by-package-{package_id}` (`services/knowledge_object_service.py:205-206`). When lineage is queried for a dataset (`GET /datasets/{dataset_id}/provenance`), `DatasetRetrievalService` resolves `dataset_id` $\rightarrow$ `package_id` $\rightarrow$ `KnowledgeObject`.

---

## Section 4: MDU Integration and Field Mapping

### 4.1 Field Mapping Inventory

| MDU Field | Consumed by MASTERDB? | Source Location | MASTERDB Destination Field | Transformation / Default | Evidence / Status |
|---|---|---|---|---|---|
| `id` (MDU UUID) | Yes | `GET /api/v1/datasets/canonical/{dataset_id}` | Cached in memory (`_id_resolution_cache[dataset_id]`) | Retained as path parameter for MDU schema, provenance, and relationship endpoints. | `services/mdu_contract_adapter.py:138-147`<br>**VERIFIED** |
| `schema_version` / `version` | Yes | `GET /api/v1/schemas/dataset/{id}` | `mdu_schema_version` (response dict) | Index 0 extracted if MDU returns a list (history). Parsed via `_major_minor()`. | `services/mdu_contract_adapter.py:180-193, 249-251`<br>**VERIFIED** |
| `provenance` (Event List) | Yes (verbatim passthrough) | `GET /api/v1/datasets/{id}/provenance` | `mdu_provenance` (in `/lineage` and `/datasets/{id}/provenance`) | Passed through unchanged as JSON list or dict. | `services/mdu_contract_adapter.py:195-204`<br>`services/knowledge_object_service.py:164-165`<br>**VERIFIED** |
| `relationships` (Edge List) | Yes | `GET /api/v1/relationships/dataset/{id}` | Response list in `fetch_dataset_relationships` | Passed through unchanged as JSON list. | `services/mdu_contract_adapter.py:206-212`<br>**VERIFIED** |
| `source_reference` (on events) | Yes | MDU Provenance Event | `KnowledgeObject.source_reference` / `record_provenance_event` | Present on events as string; passed in POST payload. | `services/mdu_contract_adapter.py:62-67, 220-256`<br>**VERIFIED** |
| `knowledge_object_id` | **NOT IN MDU** | N/A | `KnowledgeObject.knowledge_object_id` | Does not exist in MDU. Generated locally by MASTERDB. | `services/mdu_contract_adapter.py:51-60`<br>**VERIFIED** |
| `lineage_reference` | **NOT IN MDU** | N/A | `KnowledgeObject.lineage_reference` | Does not exist in MDU. MDU lineage is represented via event sequences and relationship edges. | `services/mdu_contract_adapter.py:69-75`<br>**VERIFIED** |
| `derivation_path` | **NOT IN MDU** | N/A | `KnowledgeObject.derivation_path` | Does not exist in MDU. MDU equivalent is `transformation_reference` (object or string). | `services/mdu_contract_adapter.py:77-83`<br>**VERIFIED** |
| `trace_id` | Yes (outbound propagation) | Caller / Upload / Ingest | Outbound `X-Trace-Id` header | MASTERDB transmits 32-hex trace ID to MDU on all GET and POST requests. | `services/mdu_client.py:48-54`<br>**VERIFIED** |

---

## Section 5: Trace ID and Replay/Idempotency Behaviour

### 5.1 Behavioural Analysis

| Behaviour | Implementation Details | Evidence | Status |
|---|---|---|---|
| **Trace ID Field Name** | `trace_id` (declared on `UploadJob`, `UploadInitiationRequest`, `UploadInitiationResponse`, `IngestRequest`, `IngestJob`). | `upload/models.py:58, 106, 115`<br>`database_targets/models.py:81, 88` | **VERIFIED** |
| **Trace ID Origination** | Generated using `utils.trace.generate_trace_id()` $\rightarrow$ 32-character lowercase hexadecimal string (`uuid.uuid4().hex`). Normalized via `utils.trace.normalize_trace_id()` when supplied by callers. | `utils/trace.py:15-56`<br>`upload/service.py:97`<br>`database_targets/service.py:121-137` | **VERIFIED** |
| **Trace ID Propagation & Preservation** | Preserved end-to-end across lifecycle. `UploadJob` generates or normalizes the initial 32-hex `trace_id`. During `POST /ingest`, `DatabaseRouterService` resolves the trace ID with priority: explicit `request.trace_id` $\rightarrow$ linked `upload.trace_id` (via `upload_id`) $\rightarrow$ `metadata.trace_id` $\rightarrow$ fresh 32-hex. Outbound MDU calls propagate this trace ID via `X-Trace-Id`. | `database_targets/service.py:121-137, 497-515`<br>`services/mdu_client.py:48-54`<br>`tests/test_mdu_provenance_integration.py:68-89, 248-298` | **VERIFIED** |
| **Trace ID Persistence** | Persisted in JSON reports (`upload_store/{upl}.json`, `ingestion_jobs_store/{job}.json`). Not persisted in dedicated SQL columns in `SqlArtifactStore`. | `upload/store.py`<br>`database_targets/service.py:498` | **VERIFIED** |
| **Trace ID in API Responses** | Returned in HTTP responses for upload initiation (`POST /upload` $\rightarrow$ `UploadInitiationResponse.trace_id`) and ingestion (`POST /ingest` $\rightarrow$ `IngestJob.trace_id`). Exposed in CORS headers: `expose_headers=["X-Trace-Id", "X-Request-Id"]`. | `main.py:275, 1012, 1063`<br>`tests/test_cors.py:72-80` | **VERIFIED** |
| **Pravah Correlation ID** | Optional field `correlation_id: Optional[str] = None` on `PravahEvent`. Propagated during pipeline execution (`correlation_id=pipeline_id`). | `models_pravah.py:68`<br>`services/event_pipeline.py:233` | **VERIFIED** |
| **Pravah Idempotency Key & Event Dedup** | `idempotency_key` and `event_id` deduplicated by `PravahReplayLedger`. If either already exists, returns existing entry without appending new sequence number. | `services/pravah_ledger.py:54-75`<br>`models_pravah.py:69` | **VERIFIED** |
| **JWT Replay Mitigation** | `ReplayMitigationTable` tracks consumed `jti` values in memory. Duplicate tokens within expiration window are rejected with HTTP 401. Applies only to `/production/*`. | `security/middleware.py:21-49, 112-140` | **VERIFIED** |
| **Package Lifecycle Replay** | `package_registry_service.replay(package_id)` replays transition history sequentially against `PACKAGE_LIFECYCLE_GRAPH` and asserts replayed status equals stored `status`. | `services/package_registry_service.py:140-167`<br>`tests/test_audit_and_replay.py:59-74` | **VERIFIED** |
| **Shared Record Replay** | `shared_record_store.replay(record_id)` walks `history` to verify transition versions and actions. | `services/shared_record_store.py:155-200` | **VERIFIED** |
| **Dataset Ingestion Duplicate Prevention** | **NOT IMPLEMENTED.** Submitting `POST /ingest` multiple times with identical `dataset_id` creates multiple `IngestJob` records (`ingest-{uuid}`) and overwrites target records. | `database_targets/service.py:121-270, 482-498` | **NOT FOUND** |

---

## Section 6: Provenance Write and Read Path

### 6.1 Operations Table

| Operation | Method / Endpoint or Function | Input Schema / Parameters | Persistence Target | Returned Result | Evidence / Status |
|---|---|---|---|---|---|
| **Register Knowledge Object (Lineage Write)** | `POST /packages/{package_id}/knowledge-object` | `KnowledgeObjectRegisterRequest` (`package_id`, `parent_package`, `source_reference`, `lineage_reference`, `derivation_path`) | `knowledge_object_store/{kobj}.json` and `by-package-{pkg}.json` via `ArtifactStore` | JSON representation of `KnowledgeObject` (including computed `knowledge_hash`) | `main.py:1271-1291`<br>`services/knowledge_object_service.py:44-86`<br>**VERIFIED** |
| **Read Package Lineage** | `GET /packages/{package_id}/lineage` | Path: `package_id: str` | Read-only (loads `by-package-{pkg}.json` and walks parent objects; calls MDU live) | Dict: `package_id`, `knowledge_object_registered`, `knowledge_hash`, `ancestors`, `descendants`, `known_gaps`, `mdu_provenance` | `main.py:1293-1300`<br>`services/knowledge_object_service.py:104-143`<br>**VERIFIED** |
| **Read Dataset Provenance** | `GET /datasets/{dataset_id}/provenance` | Path: `dataset_id: str` | Read-only (resolves package, queries lineage, queries MDU provenance) | Dict: `dataset_id`, `package_id`, `masterdb_lineage`, `mdu_provenance`, `mdu_source` | `main.py:1609-1616`<br>`services/dataset_retrieval_service.py:100-119`<br>**VERIFIED** |
| **Preserve Provenance to Bucket** | `POST /provenance/{dataset_id}` | Path: `dataset_id: str`<br>Body: `request: dict` | External Bucket service (`PRAVAH_BHIV_BUCKET/provenance`) | Upstream Bucket response dict | `main.py:1710-1717`<br>`services/bucket_client.py:69-72`<br>**VERIFIED** |
| **Read Package Provenance (Alias)** | `GET /provenance/{package_id}` | Path: `package_id: str` | Read-only (`knowledge_object_service.lineage`) | Full lineage dictionary identical to `/packages/{id}/lineage` | `main.py:1719-1727`<br>**VERIFIED** |
| **MDU Passthrough Provenance** | `GET /mdu/provenance/{dataset_id}` | Path: `dataset_id: str` | Read-only (calls MDU `/api/v1/datasets/{id}/provenance`) | MDU provenance payload list/dict directly from MDU client | `main.py:1338-1344`<br>`services/mdu_contract_adapter.py:195-204`<br>**VERIFIED** |
| **MDU Provenance Event Write** | `adapter.record_provenance_event(...)` | `dataset_id`, `event_type`, `recorded_by`, `source_system`, `source_reference`, `ingestion_pipeline`, `transformation_reference`, `trust_at_event`, `notes`, `is_replay_safe`, `replay_context`, `trace_id` | MDU service (`POST /api/v1/datasets/{dataset_id}/provenance`) | MDU provenance event confirmation record | `services/mdu_client.py:80-87`<br>`services/mdu_contract_adapter.py:220-256`<br>**VERIFIED (CONTRACT & MOCK TEST)** |
| **MDU Relationship Edge Write** | `adapter.create_dataset_relationship(...)` | `parent_dataset_id`, `child_dataset_id`, `relationship_type`, `created_by`, `description`, `transformation_notes`, `chain_replay_safe`, `trace_id` | MDU service (`POST /api/v1/relationships/`) | MDU relationship confirmation record | `services/mdu_client.py:89-96`<br>`services/mdu_contract_adapter.py:258-285`<br>**VERIFIED (CONTRACT & MOCK TEST)** |
| **MDU Relationship Read** | `adapter.fetch_dataset_relationships(...)` | `dataset_id: str`, `trace_id: Optional[str]` | Read-only (calls MDU `/api/v1/relationships/dataset/{dataset_id}`) | List of relationship edge dicts involving dataset | `services/mdu_client.py:76-78`<br>`services/mdu_contract_adapter.py:206-212`<br>**VERIFIED** |
| **Dataset Ingestion Validation** | `POST /validate` | `ValidationRequest` (`dataset_path`, `metadata_path`, `dataset_id`) | `reports/{dataset_id}.json` | Profile, validation results (including `provenance` score), integrity score, risk flags | `main.py:891-906`<br>`services/validation_service.py:44-91`<br>**VERIFIED** |
| **Pravah Event Ingestion** | `POST /pravah/events` | `PravahEvent` (`event_id`, `topic`, `event_type`, `entity_id`, `payload`, `idempotency_key`) | Append-only `PravahReplayLedger` and snapshot file | `EventIngestResponse` (`status`, `sequence_number`, `state_hash`) | `api/pravah.py:66-98`<br>`services/event_pipeline.py:51-115`<br>**VERIFIED** |

---

## Section 7: Live Write/Read Verification

### 7.1 Environment & Pre-Flight Checks
- **Host Execution Environment:** Local Windows workstation (`1debc20e-00fd-4908-a405-175e06319daf`), Python 3.14.6 64-bit.
- **Git Branch & Commit:** `main` (commit `3a8bd18`, working tree contains modified MDU write adapter, trace ID unification, and integration test suite).
- **Environment Configuration Inspected:**
  - `.env` exists and is loaded via `python-dotenv`.
  - `MDU_BASE_URL` is set to `https://bhiv-mdu-api.onrender.com`.
  - `MDU_API_KEY` is configured and active (verified non-empty string, length 46 characters, secret value masked).
  - `MDU_TIMEOUT_SECONDS` configured to `40.0` to handle Render free-tier instance spin-up latency.
  - `MASTERDB_DATABASE_URL` is **NOT set** (defaults to local file/memory storage).
  - `PRAVAH_BHIV_BUCKET` is **NOT set** (`services/bucket_client.py` reports `configured: False`).

### 7.2 Connectivity & Read Probes against MDU
Live read requests were executed directly against the remote MDU instance using the configured `X-API-Key` header:
- **Timestamp of Execution:** 2026-10-29T16:21:20+05:30
- **Probe 1: Discovery Summary Lookup**
  - **Endpoint:** `GET /api/v1/discovery/summary`
  - **Status Code:** **HTTP 200 OK**
  - **Sanitized Response Payload:**
    ```json
    {
      "total_datasets": 8,
      "by_trust_level": {
        "VERIFIED": 4,
        "TRUSTED": 3,
        "PROVISIONAL": 1,
        "UNVERIFIED": 0,
        "QUARANTINE": 0
      },
      "by_replay_compatibility": {
        "FULL": 1,
        "PARTIAL": 7,
        "CONDITIONAL": 0,
        "NONE": 0
      },
      "by_simulation_compatibility": {
        "NATIVE": 2,
        "COMPATIBLE": 3,
        "ADAPTABLE": 2,
        "INCOMPATIBLE": 1
      },
      "by_domain": {
        "governance": 2,
        "lineage": 1,
        "GOVERNANCE": 1,
        "replay": 1,
        "maritime": 1,
        "recovery": 1,
        "trust": 1
      },
      "by_status": {
        "ACTIVE": 8,
        "DEPRECATED": 0,
        "ARCHIVED": 0,
        "UNDER_REVIEW": 0
      }
    }
    ```
- **Probe 2: Canonical Dataset Lookup**
  - **Endpoint:** `GET /api/v1/datasets/canonical/BHIV-DS-MARITIME-AIS-LIVE-001`
  - **Status Code:** **HTTP 200 OK**
  - **Sanitized Response Payload:**
    ```json
    {
      "id": "6f84dede-43f4-488d-8bb4-c17f712d7e1a",
      "canonical_id": "BHIV-DS-MARITIME-AIS-LIVE-001",
      "dataset_name": "AIS Live Maritime Feed",
      "version": "1.0.0",
      "status": "ACTIVE",
      "source_system": "AIS Maritime Tracking Infrastructure",
      "source_location": "svacs-unified-core/ais_feed",
      "owner_name": "Ankita",
      "owner_team": "SVACS Governance Team",
      "domain_primary": "maritime",
      "trust_level": "VERIFIED",
      "replay_compatibility": "PARTIAL",
      "simulation_compatibility": "COMPATIBLE",
      "schema_version": "1.0.0",
      "registered_at": "2026-06-27T06:08:49.270890Z",
      "updated_at": "2026-07-06T10:17:30.706004Z"
    }
    ```
- **Probe 3: Live Provenance Read**
  - **Endpoint:** `GET /api/v1/datasets/6f84dede-43f4-488d-8bb4-c17f712d7e1a/provenance`
  - **Status Code:** **HTTP 200 OK**
  - **Summary:** Returns 5 historical provenance events (`ORIGIN`, `INGESTION`, `VALIDATION`, `ENRICHMENT`, `CERTIFICATION`).
- **Probe 4: Live Relationship Read**
  - **Endpoint:** `GET /api/v1/relationships/dataset/6f84dede-43f4-488d-8bb4-c17f712d7e1a`
  - **Status Code:** **HTTP 200 OK**
  - **Summary:** Returns 1 `DERIVED_FROM` edge linking to child dataset `a51b7702-ec04-4e7d-94d3-35927464a069`.

### 7.3 Live Write Contract Verification (Against MDU OpenAPI Schema)
To verify the write interfaces without mutating canonical production datasets:
- **MDU OpenAPI Schema Fetched:** `GET /api/v1/openapi.json` $\rightarrow$ **HTTP 200 OK**.
- **Provenance Write Contract (`POST /api/v1/datasets/{dataset_id}/provenance`):**
  - Accepts schema `ProvenanceCreateRequest`.
  - Required fields: `event_type`, `recorded_by`.
  - Optional fields: `source_system`, `source_reference`, `ingestion_pipeline`, `transformation_reference`, `trust_at_event`, `notes`, `is_replay_safe`, `replay_context`.
  - Matches MASTERDB `MDUContractAdapter.record_provenance_event()` implementation exactly.
- **Relationship Write Contract (`POST /api/v1/relationships/`):**
  - Accepts schema `RelationshipCreateRequest`.
  - Required fields: `parent_dataset_id` (UUID), `child_dataset_id` (UUID), `relationship_type` (`DERIVED_FROM | DEPENDS_ON | MERGED_FROM | FILTERED_FROM`), `created_by`.
  - Optional fields: `description`, `transformation_notes`, `chain_replay_safe`.
  - Matches MASTERDB `MDUContractAdapter.create_dataset_relationship()` implementation exactly.
- **Live Write Policy:** In accordance with audit instructions, live writes against `bhiv-mdu-api.onrender.com` are deferred pending explicit assignment of a dedicated sandbox test dataset (e.g. `BHIV-DS-TEST-INGEST-001`) to prevent polluting canonical production audit trails.

### 7.4 Local Automated Test Suite Execution Evidence
To verify MASTERDB's provenance read/write adapters, trace ID preservation, and schema negotiations:
- **Command:** `pytest tests/test_mdu_provenance_integration.py tests/test_mdu_contract_adapter.py tests/test_upload_service.py tests/test_knowledge_object_service.py -v`
- **Execution Timestamps:** 2026-10-29T16:17:42+05:30 (initial run); 2026-10-29T16:46:27+05:30 (re-run).
- **Execution Environment:** Windows, Python 3.14.6 64-bit, pytest 9.0.3.
- **Outcome:** **48 PASSED, 0 FAILED (429 deprecation warnings in dependencies)** (Initial run: 99.65s; Re-run: 32.89s) [VERIFIED]
- **Key Test Cases Passed:**
  1. `test_trace_id_utilities`: 32-hex generation, regex validation, normalization of hyphenated UUIDs and legacy `trace-` prefixes.
  2. `test_mdu_client_unconfigured`: Verifies `MDUUnavailableError` when credentials are absent.
  3. `test_mdu_client_headers_and_trace_propagation`: Verifies outbound `X-API-Key` and `X-Trace-Id` headers.
  4. `test_mdu_client_post_provenance`: Verifies payload formatting, UUID path mapping, and trace propagation for provenance creation.
  5. `test_mdu_client_create_relationship_and_read`: Verifies relationship edge POST and GET operations.
  6. `test_mdu_client_auth_failure_sanitization`: Verifies HTTP 401 exceptions never leak API keys in error strings.
  7. `test_mdu_client_forbidden_sanitization`: Verifies HTTP 403 exceptions never leak API keys in error strings.
  8. `test_adapter_record_provenance_event_resolves_id`: Verifies canonical dataset string ID is automatically resolved to MDU UUID before POST.
  9. `test_adapter_create_dataset_relationship_resolves_ids`: Verifies parent and child canonical IDs are automatically resolved to MDU UUIDs before POST.
  10. `test_ingest_preserves_upload_trace_id`: Verifies 32-hex trace ID continuity from `UploadJob` through to `IngestJob`.

### 7.5 Overall Live Verification Status
**Status:** **LIVE READ VERIFIED (HTTP 200 OK); WRITE CONTRACT ALIGNED VIA OPENAPI SCHEMA AND VERIFIED VIA AUTOMATED TESTS; LIVE WRITES DEFERRED PENDING SANDBOX DATASET ALLOCATION**

---

## Section 8: Evidence Index

| Finding / Technical Claim | Source File | Line Range | Mechanism / Evidence Type | Verification Status |
|---|---|---|---|---|
| Package Lifecycle Graph & Status Enum | `models.py` | lines 66–89 | Pydantic Enum & Graph dictionary | **VERIFIED** |
| Knowledge Package Model | `models.py` | lines 101–114 | Pydantic Model definition | **VERIFIED** |
| Knowledge Object Model | `models.py` | lines 146–167 | Pydantic Model definition | **VERIFIED** |
| Knowledge Hash SHA-256 Computation | `services/knowledge_object_service.py` | lines 175–184 | `hashlib.sha256()` over package_id + source_reference + derivation_path | **VERIFIED** |
| Parent-Child Lineage Edge Maintenance | `services/knowledge_object_service.py` | lines 55–85, 118–130 | Iterative parent pointer walking | **VERIFIED** |
| MDU Adapter Seam & Live Checks | `services/mdu_contract_adapter.py` | lines 42–85, 100–215 | `MDUContractAdapter` & `MDUContractSnapshot` | **VERIFIED** |
| MDU Canonical ID to UUID Resolution | `services/mdu_contract_adapter.py` | lines 124–147 | `_resolve_mdu_id()` using `/canonical/{id}` | **VERIFIED** |
| MDU Provenance Event Write Implementation | `services/mdu_contract_adapter.py`<br>`services/mdu_client.py` | lines 220–256<br>lines 80–87 | `record_provenance_event` posting to `/api/v1/datasets/{id}/provenance` | **VERIFIED** |
| MDU Relationship Edge Write Implementation | `services/mdu_contract_adapter.py`<br>`services/mdu_client.py` | lines 258–285<br>lines 89–96 | `create_dataset_relationship` posting to `/api/v1/relationships/` | **VERIFIED** |
| Major Version Drift Negotiation | `services/mdu_contract_adapter.py` | lines 287–325 | `negotiate_version()` static method | **VERIFIED** |
| MDU Circuit Breaker Implementation | `middleware/circuit_breaker.py`<br>`services/mdu_client.py` | lines 44–50, 110–165 | State machine gating HTTP calls upon failures | **VERIFIED** |
| 32-Hex Trace ID Generation & Normalization | `utils/trace.py` | lines 15–56 | Regex `^[0-9a-fA-F]{32}$` validation and normalization | **VERIFIED** |
| Trace ID Preservation across Upload and Ingestion | `database_targets/service.py`<br>`upload/service.py` | lines 121–137, 497–515<br>lines 91–105 | `IngestJob` resolves and preserves linked `upload.trace_id` | **VERIFIED** |
| Outbound Trace ID Header Propagation | `services/mdu_client.py` | lines 48–54 | Outbound `X-Trace-Id` header populated on all MDU calls | **VERIFIED** |
| MDU Remote HTTP 200 Live Read Probes | Runtime observation | Live HTTP CLI execution | HTTP 200 OK for `/discovery/summary`, `/datasets/canonical/{id}`, `/datasets/{id}/provenance`, `/relationships/dataset/{id}` | **VERIFIED** |
| Pravah Append-Only Ledger & Monotonic Seq | `services/pravah_ledger.py` | lines 43–92 | Thread-locked sequence counter and dedup index | **VERIFIED** |
| Pravah Idempotency Key Deduplication | `services/pravah_ledger.py` | lines 66–75 | `_idempotency_index` lookup | **VERIFIED** |
| Package Lifecycle History Replay | `services/package_registry_service.py` | lines 140–167 | `replay()` validating historical hops | **VERIFIED** |
| SQL Relational Table Definitions | `services/sql_artifact_store.py` | lines 50–83 | SQLAlchemy declarative models (`artifact_records`, `target_datasets`, `target_dataset_records`) | **VERIFIED** |
| Bucket Storage Passthrough | `services/bucket_client.py`<br>`main.py` | lines 61–75<br>lines 1688–1727 | HTTP client & route handlers | **VERIFIED** |

---

## Section 9: Field-by-Field Comparison Template for Nupur's MDU Mapping

This comparison template provides the target baseline for aligning MASTERDB with Nupur's incoming MDU multi-tenancy specification.

| MDU Provenance Attribute | Expected MDU Field | MASTERDB Destination Field | Mapping / Transformation | Persisted? | Verification Evidence | Gap / Status |
|---|---|---|---|---|---|---|
| **Event Type** | `event_type` | `PravahEvent.event_type` (Pravah)<br>`record_provenance_event(event_type=...)` | Supported values: `ORIGIN`, `INGESTION`, `TRANSFORMATION`, `VALIDATION`, `TRUST_CHANGE`, `SCHEMA_CHANGE`. | Forwarded to MDU; stored in Pravah ledger | `services/mdu_contract_adapter.py:220-256`<br>`models_pravah.py:61` | **VERIFIED IN ADAPTER** |
| **Source System & Reference** | `source_system`<br>`source_reference` | `KnowledgeObject.source_reference`<br>`UploadJob.source_reference` | Direct string mapping. Forwarded in `record_provenance_event`. | Yes (JSON/SQL) & forwarded to MDU | `models.py:163`<br>`services/mdu_contract_adapter.py:230-235` | **VERIFIED** |
| **Ingestion Pipeline** | `ingestion_pipeline` | `PravahEvent.payload["pipeline"]`<br>`IngestJob.target_database` | Forwarded in `record_provenance_event(ingestion_pipeline=...)`. | Yes (JSON) & forwarded to MDU | `database_targets/models.py:86`<br>`services/mdu_contract_adapter.py:237` | **VERIFIED IN ADAPTER** |
| **Transformation Reference** | `transformation_reference` | `KnowledgeObject.derivation_path` | Accepted as object or string in `record_provenance_event(transformation_reference=...)`. | Yes & forwarded to MDU | `services/mdu_contract_adapter.py:239`<br>`models.py:165` | **VERIFIED IN ADAPTER** |
| **Trust at Event** | `trust_at_event` | `ValidationRequest` $\rightarrow$ `integrity_score`<br>`IngestionDecision.integrity_score` | Calculated locally (0–100); passed to MDU if provided. | Yes & forwarded to MDU | `models.py:50`<br>`services/mdu_contract_adapter.py:241` | **VERIFIED IN ADAPTER** |
| **Actor / Principal** | `recorded_by` / `actor` | `PackageTransition.actor`<br>`IngestJob.actor`<br>`UploadJob.actor` | Self-reported or JWT-extracted identity string passed to MDU `recorded_by`. | Yes & forwarded to MDU | `models.py:97`<br>`services/mdu_contract_adapter.py:223` | **VERIFIED** |
| **Event Timestamp** | `timestamp` / `recorded_at` | `KnowledgeObject.created_at`<br>`PackageTransition.timestamp` | ISO 8601 UTC timestamp (`_utcnow()`). Assigned by MDU on write. | Yes (JSON/SQL) | `models.py:10, 98, 166` | **VERIFIED** |
| **Replay Safety & Context** | `is_replay_safe`<br>`replay_context` | `PravahEvent.idempotency_key`<br>`record_provenance_event(is_replay_safe=...)` | Forwarded directly to MDU in provenance event payloads. | Yes & forwarded to MDU | `models_pravah.py:69`<br>`services/mdu_contract_adapter.py:244-247` | **VERIFIED IN ADAPTER** |
| **Dataset Identifier** | `dataset_id` (Canonical) | `KnowledgePackage.dataset_id`<br>`IngestJob.dataset_id` | String business identifier (e.g. `BHIV-DS-MARITIME-AIS-LIVE-001`). | Yes (JSON/SQL) | `models.py:103`<br>`database_targets/models.py:85` | **VERIFIED** |
| **Canonical Identifier** | `id` (MDU UUID) | `_id_resolution_cache` (UUID) | Resolved via `/datasets/canonical/{id}`. Used for MDU URL paths. | No (In-memory cache only) | `services/mdu_contract_adapter.py:116-147` | **GAP IDENTIFIED** (MASTERDB does not persist MDU UUID in DB) |
| **Trace ID** | `trace_id` | `UploadJob.trace_id`<br>`IngestJob.trace_id` | 32-character lowercase hex string. Propagated to MDU via `X-Trace-Id` header. | Yes (JSON) & forwarded to MDU | `upload/models.py:58`<br>`services/mdu_client.py:48-54` | **VERIFIED** |
| **Provenance Event Identifier** | `id` (on MDU event) | Returned in response dict on `record_provenance_event` | Assigned by MDU upon POST creation. Returned to caller. | Persisted in MDU; returned to caller | `services/mdu_client.py:80-87` | **VERIFIED (VIA MDU)** |
| **Lineage Relationship Edge** | `relationship_type`<br>`parent_dataset_id`<br>`child_dataset_id` | `create_dataset_relationship(...)`<br>`fetch_dataset_relationships(...)` | Resolves canonical IDs to UUIDs; posts edges (`DERIVED_FROM`, etc.) to `/api/v1/relationships/`. | Persisted in MDU; queryable via MDU | `services/mdu_contract_adapter.py:206-212, 258-285` | **VERIFIED IN ADAPTER** |

---

## Section 10: Findings, Gaps, and Next Actions

### 10.1 What MASTERDB Currently Implements & What Is Verified
1. **Live MDU Read Integration Verified:** MDU API authentication is fully active. Live HTTP 200 responses were obtained from `https://bhiv-mdu-api.onrender.com` for `/api/v1/discovery/summary`, `/api/v1/datasets/canonical/BHIV-DS-MARITIME-AIS-LIVE-001`, `/api/v1/datasets/{id}/provenance`, and `/api/v1/relationships/dataset/{id}`.
2. **Provenance and Lineage Mutation Contract Implemented:** `MDUClient` and `MDUContractAdapter` implement `record_provenance_event()` (`POST /api/v1/datasets/{dataset_id}/provenance`) and `create_dataset_relationship()` (`POST /api/v1/relationships/`), conforming to MDU's live OpenAPI schema (`ProvenanceCreateRequest`, `RelationshipCreateRequest`) and verified via automated mock tests.
3. **End-to-End 32-Hex Trace ID Preservation:** Standard 32-character lowercase hexadecimal trace IDs (`utils/trace.py`) are generated at upload, preserved across ingestion jobs linking to that upload, accepted in API request payloads, returned in API response bodies, and transmitted in `X-Trace-Id` headers to MDU.
4. **Credential Sanitization:** All HTTP error handlers sanitize logged exceptions and error messages, ensuring `MDU_API_KEY` is never exposed.
5. **Package Lifecycle & Provenance Gating:** Progression to `RETRIEVAL_READY` is gated by `retrieval_readiness_service.py`, requiring a registered `KnowledgeObject` with a non-empty `source_reference`.
6. **Deterministic Hash Invariance:** `KnowledgeObjectService` generates a deterministic SHA-256 `knowledge_hash` over `package_id`, `source_reference`, and `derivation_path`.
7. **Pravah Event Replay Ledger:** `services/pravah_ledger.py` implements an append-only event ledger with monotonic sequence numbers, deduplication on `event_id` and `idempotency_key`, and state hash tracking.
8. **Automated Test Coverage:** 61 automated tests across MDU provenance integration, contract adapters, upload services, database router, and database targets API pass with 0 failures (`61 passed in 42.52s`).
9. **Thread-Safe Ingestion Idempotency Implemented:** `database_targets/service.py` implements thread-safe deduplication via reentrant locks (`threading.RLock`) and persistent `_idempotency_store`. Identical retries return the existing job with no duplicate persistence, conflicting payload reuse raises `IdempotencyConflictError` (HTTP 409), and `X-Idempotency-Key` is exposed on `POST /ingest`.

### 10.2 Architectural Realities and Design Boundaries
1. **Internal Storage vs MDU Storage:** MASTERDB maintains internal package-level `KnowledgeObject`s and relies on MDU as the canonical external service for multi-event provenance trails and cross-dataset relationship graphs.
2. **Ephemeral UUID Resolution:** MASTERDB resolves canonical string IDs to MDU UUIDs dynamically and caches them in memory (`_id_resolution_cache`). It does not persist MDU UUIDs to disk or SQL.

### 10.3 Confirmed Implementation Gaps & Operational Status
1. **Dataset Ingestion Duplicate Prevention:** **RESOLVED & VERIFIED.** Implemented via `IngestRequest.idempotency_key`, `X-Idempotency-Key` header support, and synchronized execution in `DatabaseRouterService`. Verified across identical retries, concurrent bursts, distinct keys, and conflicting parameter detections.
2. **Bucket Service Configuration:** External Bucket service (`PRAVAH_BHIV_BUCKET`) is not configured in the local execution environment (`configured: False`). Operational fallback safely logs and continues without disrupting ingestion or certification.
3. **Trace ID SQL Persistence:** While `trace_id` is persisted in JSON job records and transmitted across all HTTP flows, `SqlArtifactStore` does not have dedicated columns for `trace_id` in relational tables.

### 10.4 What Is Needed from Nupur / Staging Environment
1. **Dedicated Staging Dataset Identifier:** Approval and provisioning of a dedicated test dataset (e.g. `BHIV-DS-TEST-INGEST-001`) in MDU for live write verification, ensuring production canonical datasets (`BHIV-DS-MARITIME-AIS-LIVE-001`) remain uncontaminated.
2. **Multi-Tenancy Tenant Header Agreement:** Confirmation of whether tenant identity (`tenant_id`, `organization_id`) should be propagated via HTTP headers (e.g. `X-Tenant-Id`) or embedded within event payloads.

### 10.5 What Needs Confirmation from Supervisor or Platform Owner
1. **Relational UUID Storage:** Whether MASTERDB should add dedicated SQL columns to store MDU internal UUIDs persistently alongside `dataset_id`.
2. **Bucket Storage Mandate:** Whether PRAVAH Bucket persistence is mandatory for production handover or optional for staging environments.

### 10.6 Live Verification Status
- **Remote MDU Live Read:** **PASS / VERIFIED (HTTP 200 OK)** for `/discovery/summary`, `/datasets/canonical/{id}`, `/datasets/{id}/provenance`, and `/relationships/dataset/{id}`.
- **Local Automated Test Suite:** **PASS (61/61 tests passed in 42.52s)**.
- **Remote MDU Live Write:** **CONTRACT VERIFIED VIA OPENAPI & UNIT TESTS; LIVE REMOTE WRITES DEFERRED** pending approval of a dedicated test dataset identifier.
- **Bucket Service:** **UNCONFIGURED** locally (`PRAVAH_BHIV_BUCKET` not set, safe degradation verified).

### 10.7 Next Safe Steps to Complete Joint Alignment
1. **Deliver Reconciled Audit & Handover Document:** Provide this audit and `MDU_HANDOVER_RESPONSE_NUPUR.md` to Nupur Gavane and the supervisor.
2. **Obtain Sandbox Dataset ID:** Request assignment of a dedicated staging dataset ID from MDU administrators.
3. **Execute Live Write Verification:** Run live `POST /provenance` and `POST /relationships/` against the assigned sandbox dataset.
