# MASTERDB–MDU Provenance and Lineage Reconciliation Draft

**Document Target:** Joint MDU–MASTERDB Technical Reconciliation  
**Sprint / Priority:** BIQOS P0 Joint Priority  
**MASTERDB Owner:** Kavy Changela (Senior Backend Engineer, MASTERDB)  
**MDU Owner:** Nupur Gavane (MDU Semantic Authority)  
**Supervisor / Reviewer:** Raj (BIQOS Lead)  
**Date:** 2026-11-04  
**Primary Repository:** `Kavychangela/masterdb-ingestion-certification-service`  
**Status:** MASTERDB-Side Draft (Pending Joint Confirmation with Nupur)  

---

## 1. Executive Summary & Context

Under Raj's BIQOS P0 directive, this document establishes MASTERDB's authoritative technical position, field mapping, lifecycle boundary, and validation criteria for reconciling provenance and lineage with MDU.

### Key Evidential Foundations
1. **Separation of Concerns:** MDU owns the semantic truth, multi-event append-only provenance log, cross-dataset relationship graphs, and schema version contracts. MASTERDB owns the intake pipeline, file/object validation, package version transitions, database ingestion routing, and local package retrieval readiness.
2. **On-Demand Consumption:** MASTERDB does not maintain an independent multi-event duplicate provenance store. It resolves canonical dataset identifiers to MDU UUIDs dynamically, fetches verified provenance on-demand from MDU, and degrades gracefully to local fallback metadata if MDU is unreachable.
3. **Trace Continuity:** Outbound requests from MASTERDB propagate standardized 32-character lowercase hexadecimal trace IDs (`X-Trace-Id`) conforming to W3C distributed tracing standards.
4. **Current Implementation Baseline:** Verified against the active MASTERDB codebase and test suites (`pytest tests/test_mdu_provenance_integration.py tests/test_mdu_contract_adapter.py -v` — 21/21 passing).

---

## 2. MASTERDB Technical Position

### A. Knowledge Object Identity
- **MASTERDB Identifier:** `knowledge_object_id` (format: `kobj-{12-hex}`, e.g., `kobj-d8c7fc9168e5`). Stored in `knowledge_object_store/{id}.json` and relational backends (`models.py:157`).
- **MDU Identifier:** MDU does not recognize the concept of a "Knowledge Object." MDU operates at dataset granularity (`dataset_id` as UUID, `canonical_id` as business key, e.g., `BHIV-DS-MARITIME-AIS-LIVE-001`), and provenance event granularity (`id` as UUID on `ProvenanceRecord`).
- **Identity Preservation:** MASTERDB preserves MDU's canonical dataset identifier (`dataset_id`) on every `KnowledgePackage` (`models.py:103`). It does not invent or alter MDU's canonical business key.
- **Internal Identifiers:** MASTERDB generates `knowledge_object_id` for package-level metadata encapsulation and `package_id` (`pkg-{12-hex}`) for versioned release units. When interacting with MDU, MASTERDB resolves its local `dataset_id` to MDU's internal UUID via `_resolve_mdu_id()` (`services/mdu_contract_adapter.py:124-147`).

### B. Source Reference
- **Reception:** Received at ingestion intake via `KnowledgeObjectCreateRequest` or `UploadRequest`.
- **Expected Fields:** `source_reference` (string, URI or physical origin, e.g., `"svacs-unified-core/ais_feed"` or `"s3://lake/raw/ais.csv"`).
- **Storage & Validation:** Persisted in `KnowledgeObject.source_reference` (`models.py:163`). Validated by `RetrievalReadinessService` under rule `LINEAGE_REGISTERED`: non-empty `source_reference` is strictly required for retrieval readiness.
- **Pass-through to MDU:** Passed verbatim to MDU's `ProvenanceCreateRequest.source_reference` via `MDUContractAdapter.record_provenance_event()`.

### C. Lineage Reference
- **Reception & Expected Fields:** `lineage_reference` (`Optional[str]`) on `KnowledgeObject` (`models.py:164`).
- **MDU Alignment:** In MDU OpenAPI v1, lineage is not a scalar pointer field; it is the ordered collection of historical `ProvenanceRecord`s and `RelationshipResponse` edges. MASTERDB uses `lineage_reference` to store external graph edge pointers (e.g., MDU relationship UUID `mdu-rel-7be14e3d6b0e`).
- **Validation:** MASTERDB validates parent-child package relationships internally within `PackageRegistryService`. External multi-hop graph validation is delegated entirely to MDU (`GET /api/v1/discovery/provenance/validate/{dataset_id}`).

### D. Derivation Path
- **Representation:** Stored as an ordered list of strings (`derivation_path: List[str]`, e.g., `["filter_geo_bounds", "normalize_timestamps", "deduplicate_mmsi"]`) on `KnowledgeObject` (`models.py:165`).
- **Cryptographic Lineage:** Included in the SHA-256 digest `knowledge_hash` (`services/knowledge_object_service.py:176-184`), binding derivation steps directly to object integrity.
- **MDU Alignment:** Serialized as `transformation_reference` (string/JSON) when posting provenance events or `transformation_notes` when posting dataset relationships.

### E. Lifecycle and Transformation Events
- **Creation:** Initiated via `POST /upload` -> `POST /ingest` -> `PackageRegistryService.register_package()`. Automatically records local `KnowledgeObject`.
- **Updates & Version Changes:** Packages are immutable. New versions produce a distinct `package_id` linked via `parent_package`. Schema evolution is negotiated against MDU via `MDUContractAdapter.validate_schema_compatibility()`.
- **Transformations:** Recorded in `derivation_path` and emitted to MDU as `POST /api/v1/datasets/{id}/provenance` events (`event_type="ENRICHMENT"` or `"VALIDATION"`).
- **Supersession & Retirement:** Packages transition through statuses: `REGISTERED` -> `ACTIVE` -> `DEPRECATED` / `RETIRED` (`services/package_registry_service.py:90-120`). Outbound supersession edges can be emitted to MDU as `RelationshipCreateRequest(relationship_type="SUPERSEDES")`.
- **Validation & Certification:** Certification events produce an immutable `CertificationReport`. Emitted to MDU as `event_type="CERTIFICATION"`.

### F. Validation and Certification Boundary
- **MASTERDB Validations:** File integrity, schema format adherence, bounding coordinate validation (WGS84), retrieval readiness (`RetrievalReadinessService`), and idempotency (`X-Idempotency-Key`).
- **MDU Validations:** Cross-dataset referential integrity, semantic trust level assignment (`TrustLevel`), enterprise audit trail recording (`/api/v1/audit/logs`), and canonical schema history.
- **Architectural Boundary:** MASTERDB will never overwrite, redefine, or assert ownership over MDU semantic ontology.

---

## 3. MASTERDB-Side Field Mapping Table

The following table provides the exhaustive MASTERDB-side draft mapping across all required entities. Statuses are strictly classified as **Confirmed**, **Partial**, or **Unresolved**.

| MDU Field | MASTERDB Expected Field | Mapping / Transformation Rule | Required / Optional | Source of Truth | Validation Evidence | Status | Responsible Owner |
|---|---|---|---|---|---|---|---|
| `ProvenanceRecord.id` / `dataset_id` | `knowledge_object_id` | Synthetic package-level identifier in MASTERDB (`kobj-{12-hex}`). MDU models provenance as append-only event records tied to `dataset_id`. MDU's latest provenance event UUID can be referenced via `lineage_reference`. | Required in MASTERDB; absent in MDU | MASTERDB | `models.py:157`<br>`services/knowledge_object_service.py:67-78`<br>`services/mdu_contract_adapter.py:51-60` | **Partial** | MASTERDB (Kavy) |
| `DatasetResponse.canonical_id` / `id` | `dataset_id` | 1:1 match to `canonical_id`. `_resolve_mdu_id(dataset_id)` maps canonical string ID (e.g. `BHIV-DS-MARITIME-AIS-LIVE-001`) to MDU UUID via `GET /api/v1/datasets/canonical/{id}` and caches it in memory. | Required | MDU Registry (Authoritative) / MASTERDB Registry (Referential) | `services/mdu_contract_adapter.py:124-147`<br>`models.py:103`<br>`tests/test_mdu_provenance_integration.py:8` | **Confirmed** | MDU (Nupur) / MASTERDB (Kavy) |
| `ProvenanceRecord.source_reference` | `source_reference` | Direct 1:1 string pass-through. Stored on `KnowledgeObject`, forwarded in payload of `POST /api/v1/datasets/{id}/provenance`. | Required in MASTERDB (readiness rule); Optional in MDU | MASTERDB Ingress / Upstream Feed | `models.py:163`<br>`services/retrieval_readiness_service.py:124`<br>`services/mdu_contract_adapter.py:220` | **Confirmed** | Joint (Kavy / Nupur) |
| `ProvenanceRecord.source_system` | `source_system` / `owner` | MASTERDB supplies `"MASTERDB"` or upstream pipeline identifier (e.g. `"svacs-unified-core"`) to MDU `source_system`. | Optional (defaults to `"MASTERDB"`) | MASTERDB | `services/mdu_client.py:96`<br>`services/mdu_contract_adapter.py:219` | **Confirmed** | MASTERDB (Kavy) |
| `RelationshipResponse.id` / `ProvenanceRecord.id` | `lineage_reference` | Stores external MDU relationship UUID or provenance event UUID as a foreign pointer string. MDU does not have a scalar `lineage_reference` field; its lineage is the ordered event list. | Optional | MDU | `models.py:164`<br>`services/mdu_contract_adapter.py:69-75`<br>`services/knowledge_object_service.py:137` | **Partial** | MDU (Nupur) |
| `RelationshipCreateRequest.parent_dataset_id` | `parent_package` | MASTERDB resolves `parent_package` -> parent `dataset_id` -> MDU parent UUID via `_resolve_mdu_id()`, then submits edge to `POST /api/v1/relationships/` with `relationship_type="DERIVED_FROM"`. | Optional | MASTERDB (Package hierarchy) / MDU (Dataset graph) | `services/mdu_contract_adapter.py:257-285`<br>`services/knowledge_object_service.py:118-130`<br>`tests/test_mdu_provenance_integration.py:9` | **Confirmed** | Joint (Kavy / Nupur) |
| `ProvenanceRecord.transformation_reference` / `RelationshipResponse.transformation_notes` | `derivation_path` | Serializes ordered array of transformation steps (`List[str]`) into MDU's string/JSON reference. Included in SHA-256 `knowledge_hash`. | Optional | MASTERDB | `models.py:165`<br>`services/knowledge_object_service.py:69, 177`<br>`services/mdu_contract_adapter.py:222` | **Partial** | MASTERDB (Kavy) |
| `ProvenanceRecord.replay_context` / `is_replay_safe` | `IngestJob.metadata` / `is_replay_safe` | Ingestion step audit parameters and deterministic replay flags mapped directly to MDU `replay_context` (dict) and `is_replay_safe` (bool). | Optional (defaults to `True`) | MASTERDB | `database_targets/models.py:93`<br>`services/mdu_contract_adapter.py:225-226`<br>`tests/test_mdu_provenance_integration.py:4` | **Confirmed** | MASTERDB (Kavy) |
| `DatasetResponse.status` (`DatasetStatus`) | `KnowledgePackage.status` (`PackageStatus`) | State semantic alignment: MASTERDB tracks package lifecycle (`REGISTERED`, `ACTIVE`, `DEPRECATED`, `PROMOTED`, `RETIRED`); MDU tracks dataset lifecycle (`PROVISIONAL`, `TRUSTED`, `VERIFIED`, `DEPRECATED`, `REVOKED`). | Required | MASTERDB (for Packages) / MDU (for Datasets) | `models.py:22-28`<br>`MDU-OpenAPI-v1.json:DatasetStatus` | **Partial** | Joint (Nupur / Kavy) |
| `DatasetResponse.version` / `schema_version` | `dataset_version` / `schema_version` | Major/Minor version negotiation via `MDUContractAdapter.negotiate_version()`. Exact match -> compatible; minor drift -> compatible with warning; major drift -> incompatible. | Required | MDU (Schema authority) / MASTERDB (Locally declared version) | `services/mdu_contract_adapter.py:88-98, 289-340`<br>`tests/test_mdu_contract_adapter.py:1-6` | **Confirmed** | MDU (Nupur) |
| `ProvenanceRecord.recorded_at` / `DatasetResponse.updated_at` | `created_at` / `updated_at` | Timestamps generated in ISO 8601 UTC format (`datetime.now(timezone.utc).isoformat()`). MDU's `recorded_at` is the authoritative audit timestamp. | Required | Respective recording system | `models.py:108-109, 166`<br>`MDU-OpenAPI-v1.json` | **Confirmed** | Joint (Kavy / Nupur) |
| `GET /api/v1/discovery/provenance/validate/{id}` | `RetrievalEvidence.status` / `rules_checked` | MASTERDB assesses package readiness internally; delegates graph validity assessment to MDU `/validate` probe (`valid: true`, `tantra_ready: true`). | Required for TANTRA retrieval | MDU (Graph validity) / MASTERDB (Retrieval readiness) | `services/retrieval_readiness_service.py:85-150`<br>`services/tantra_interface_service.py:153-156` | **Confirmed** | Joint (Nupur / Kavy) |
| `DatasetResponse.trust_level` (`TrustLevel`) | `IngestJob.certification_state` / `CertificationReport` | Mapping alignment needed: MASTERDB certifies ingestion quality (`CERTIFIED`); MDU records `event_type="CERTIFICATION"` and assigns enterprise `trust_level` (`AUTHORITATIVE`, etc.). | Optional at intake; required for promotion | Joint | `services/certification_service.py:1-120`<br>`database_targets/models.py:90`<br>`MDU-OpenAPI-v1.json:TrustLevel` | **Partial** | Joint (Nupur / Kavy) |
| `RelationshipResponse` (`relationship_type="SUPERSEDES"`) | `PackageTransition` / `PackageDeprecateRequest` | MASTERDB tracks package version transitions internally in `history`. Outbound supersession edge can be emitted to MDU, but automated event triggers upon package deprecation are not yet automated. | Optional | MASTERDB (Package level) / MDU (Dataset level) | `services/package_registry_service.py:90-120`<br>`services/mdu_contract_adapter.py:257-285` | **Partial** | Joint (Nupur / Kavy) |

---

## 4. Remaining Blockers & Technical Risks

| Blocker ID | Description | Technical Impact | Responsible Owner | Evidence Needed | Proposed Resolution |
|---|---|---|---|---|---|
| **BLK-01** | **Parakosha Upstream 401 Authentication Rejection** | MASTERDB cannot connect to the live Parakosha MDU replacement endpoint (`https://parakosha.blackholeinfiverse.com`). Probing `/api/v1/discovery/summary` returns HTTP 401 Unauthorized with current credentials. | MDU Registry Admin / Nupur Gavane | Valid API key provisioned on Parakosha with `CONTRIBUTOR` or `REGISTRY_ADMIN` role. | Nupur to provision an active API key for MASTERDB on Parakosha; Kavy to configure it in MASTERDB environment. |
| **BLK-02** | **Render Production Upstream Misconfiguration** | Active Render container (`bhiv-masterdb-ingestion-certification.onrender.com`) is configured with suspended URL `https://bhiv-mdu-api.onrender.com`, causing 30s timeouts on MDU calls. | DevOps / Supervisor / Kavy | Render Dashboard Environment Settings update confirmation. | Update `MDU_BASE_URL=https://parakosha.blackholeinfiverse.com` in Render dashboard after BLK-01 key provisioning. |
| **BLK-03** | **Absence of Dedicated Staging Test Dataset** | Live write operations (`POST /provenance`, `POST /relationships/`) cannot be safely verified in staging without risking pollution of production canonical dataset (`BHIV-DS-MARITIME-AIS-LIVE-001`). | MDU Semantic Authority (Nupur) | Dedicated sandbox dataset identifier (e.g. `BHIV-DS-TEST-INGEST-001`) created in MDU. | Nupur to provision a sandbox dataset; Kavy to run live write verification protocol against it. |
| **BLK-04** | **Knowledge Object Entity Gap** | MASTERDB expects `knowledge_object_id` as an entity key, whereas MDU models only datasets and event streams. | Joint (Nupur / Kavy) | Agreement on whether MDU will store `knowledge_object_id` in metadata or if it remains strictly internal to MASTERDB. | Formally classify `knowledge_object_id` as MASTERDB internal; store MDU's event UUID in `lineage_reference`. |
| **BLK-05** | **Ingress Trace ID Binding on Read Endpoints** | Read endpoints (`GET /mdu/provenance/{id}`, `GET /tantra/packages/{id}/runtime`) generate random trace IDs per call rather than binding incoming client trace IDs. | MASTERDB (Kavy) | Trace extraction middleware in `main.py`. | Add `X-Trace-Id` dependency extraction to all read routes in `main.py` to ensure end-to-end trace correlation. |

---

## 5. Technical Questions for Nupur Gavane

1. **Parakosha Credential Provisioning:** Has the new Parakosha MDU deployment (`https://parakosha.blackholeinfiverse.com`) imported the historical API keys from Render MDU, or must a new API key be generated for MASTERDB?
2. **Provenance Event Types:** What is the authoritative enumeration of `event_type` strings accepted by MDU? Current MASTERDB code uses `["ORIGIN", "INGESTION", "VALIDATION", "ENRICHMENT", "CERTIFICATION", "DEPRECATION"]`. Does MDU strictly validate this against an enum?
3. **Relationship Edge Constraints:** Does MDU require parent and child datasets to exist and have status `VERIFIED` or `TRUSTED` before accepting a `POST /api/v1/relationships/` edge?
4. **Lineage Traversal API:** Is there a single endpoint in MDU to retrieve the full ancestor tree (multi-hop graph) for a dataset, or must callers traverse pairwise edges via `GET /api/v1/relationships/dataset/{id}`?
5. **Certification Trust Synchronization:** When MASTERDB certifies a dataset, should MASTERDB emit a `POST /provenance` event with `event_type="CERTIFICATION"`, or does MDU require an explicit trust update via `PATCH /api/v1/datasets/{id}/trust`?
6. **Dedicated Sandbox Dataset:** Can you designate or create `BHIV-DS-TEST-INGEST-001` on Parakosha so we can execute our automated live-write verification test suite?

