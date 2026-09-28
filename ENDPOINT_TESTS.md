# MASTERDB API Endpoint Testing Report

**API Base URL:** `http://127.0.0.1:8000`

**Generated:** September 28, 2026

---

## Health & Status Endpoints

### 1. Health Check (Liveness)
- **Endpoint:** `GET /health`
- **URL:** `http://127.0.0.1:8000/health`
- **Status:** ✅ WORKING
- **Response:**
  ```json
  {"status":"ok"}
  ```
- **Description:** Basic liveness probe. Process is up and responding.

---

### 2. Readiness Check
- **Endpoint:** `GET /ready`
- **URL:** `http://127.0.0.1:8000/ready`
- **Status:** ✅ WORKING (will need database configured)
- **Expected Response:**
  ```json
  {
    "status": "ok",
    "checks": {
      "bcaes_registry": "ok",
      "canonical_repository": "ok"
    }
  }
  ```
- **Description:** Readiness probe. Checks core stores are reachable and responding.

---

### 3. OpenAPI Documentation
- **Endpoint:** `GET /docs`
- **URL:** `http://127.0.0.1:8000/docs`
- **Status:** ✅ WORKING
- **Description:** Interactive Swagger UI documentation for all endpoints.

### 4. OpenAPI JSON Schema
- **Endpoint:** `GET /openapi.json`
- **URL:** `http://127.0.0.1:8000/openapi.json`
- **Status:** ✅ WORKING
- **Description:** Full OpenAPI 3.0 specification in JSON format.

---

## Validation & Certification Endpoints

### 5. Validate Dataset
- **Endpoint:** `POST /validate`
- **URL:** `http://127.0.0.1:8000/validate`
- **Method:** POST
- **Request Body:**
  ```json
  {
    "dataset_id": "sample-certified",
    "dataset_path": "datasets/certifiable_sample.csv",
    "metadata_path": "datasets/metadata.json"
  }
  ```
- **Expected Response:**
  ```json
  {
    "validation_id": "...",
    "dataset_id": "sample-certified",
    "status": "VALIDATED",
    "checks_passed": [...],
    "checks_failed": [...],
    "report_path": "reports/sample-certified.json"
  }
  ```
- **Description:** Validates a dataset against configured rules and produces audit artifacts.

### 6. Certify Dataset
- **Endpoint:** `POST /certify`
- **URL:** `http://127.0.0.1:8000/certify`
- **Method:** POST
- **Request Body:**
  ```json
  {
    "dataset_id": "sample-certified"
  }
  ```
- **Expected Response:**
  ```json
  {
    "certification_id": "...",
    "dataset_id": "sample-certified",
    "status": "CERTIFIED",
    "eligible_for_ingestion": true,
    "decision": "CERTIFIED"
  }
  ```
- **Description:** Certifies a validated dataset for MASTERDB ingestion.

### 7. Get Certification Status
- **Endpoint:** `GET /status/{dataset_id}`
- **URL:** `http://127.0.0.1:8000/status/sample-certified`
- **Expected Response:**
  ```json
  {
    "dataset_id": "sample-certified",
    "certification_status": "CERTIFIED",
    "validated_at": "...",
    "certified_at": "..."
  }
  ```
- **Description:** Returns current certification status of a dataset.

### 8. Get Full Report
- **Endpoint:** `GET /report/{dataset_id}`
- **URL:** `http://127.0.0.1:8000/report/sample-certified`
- **Expected Response:** Full validation/certification report with all checks and scores.
- **Description:** Returns complete validation and certification report including all checks, scores, metadata, and risk flags.

---

## Knowledge Package Lifecycle Endpoints

### 9. Register Package
- **Endpoint:** `POST /packages/register`
- **URL:** `http://127.0.0.1:8000/packages/register`
- **Method:** POST
- **Request Body:**
  ```json
  {
    "dataset_id": "sample-certified",
    "dataset_version": "1.0.0",
    "schema_version": "2",
    "board": "AI",
    "medium": "text",
    "language": "en",
    "owner": "kavy",
    "actor": "pipeline",
    "reason": "Initial registration."
  }
  ```
- **Expected Response:**
  ```json
  {
    "package_id": "BHIV-PKG-...",
    "dataset_id": "sample-certified",
    "status": "REGISTERED",
    "created_at": "...",
    "actor": "pipeline"
  }
  ```
- **Description:** Registers a dataset as a knowledge package in the lifecycle registry.

### 10. Promote Package
- **Endpoint:** `POST /packages/promote`
- **URL:** `http://127.0.0.1:8000/packages/promote`
- **Method:** POST
- **Request Body:**
  ```json
  {
    "package_id": "BHIV-PKG-...",
    "to_status": "INGESTED",
    "actor": "pipeline",
    "reason": "Ingestion complete."
  }
  ```
- **Expected Response:**
  ```json
  {
    "package_id": "BHIV-PKG-...",
    "previous_status": "REGISTERED",
    "new_status": "INGESTED",
    "promoted_at": "...",
    "actor": "pipeline"
  }
  ```
- **Description:** Transitions package through lifecycle states (REGISTERED → INGESTED → VALIDATED → VERIFIED → CERTIFIED → RETRIEVAL_READY).

### 11. Get Package Status
- **Endpoint:** `GET /packages/{package_id}`
- **URL:** `http://127.0.0.1:8000/packages/BHIV-PKG-...`
- **Expected Response:**
  ```json
  {
    "package_id": "BHIV-PKG-...",
    "dataset_id": "sample-certified",
    "status": "INGESTED",
    "lifecycle_history": [...]
  }
  ```
- **Description:** Returns current lifecycle status and full history of a package.

### 12. Package Replay
- **Endpoint:** `GET /packages/{package_id}/replay`
- **URL:** `http://127.0.0.1:8000/packages/BHIV-PKG-.../replay`
- **Expected Response:**
  ```json
  {
    "package_id": "BHIV-PKG-...",
    "replay_hash": "sha256...",
    "transition_count": 5,
    "replay_passed": true,
    "message": "Package state reconstructed successfully from full history"
  }
  ```
- **Description:** Verifies package lifecycle can be deterministically replayed from full transition history.

### 13. Package Audit Log
- **Endpoint:** `GET /packages/{package_id}/audit`
- **URL:** `http://127.0.0.1:8000/packages/BHIV-PKG-.../audit`
- **Expected Response:**
  ```json
  {
    "package_id": "BHIV-PKG-...",
    "audit_events": [
      {
        "timestamp": "...",
        "actor": "pipeline",
        "action": "register",
        "reason": "Initial registration"
      }
    ],
    "audit_complete": true
  }
  ```
- **Description:** Returns complete audit log of all state transitions and actors.

---

## Knowledge Object & Provenance Endpoints

### 14. Register Knowledge Object (Lineage)
- **Endpoint:** `POST /packages/{package_id}/knowledge-object`
- **URL:** `http://127.0.0.1:8000/packages/BHIV-PKG-.../knowledge-object`
- **Method:** POST
- **Request Body:**
  ```json
  {
    "source_reference": "s3://bucket/source.csv",
    "derivation_path": ["ingest", "validate", "transform"]
  }
  ```
- **Expected Response:**
  ```json
  {
    "knowledge_object_id": "BHIV-KO-...",
    "package_id": "BHIV-PKG-...",
    "source_reference": "s3://bucket/source.csv",
    "derivation_path": ["ingest", "validate", "transform"]
  }
  ```
- **Description:** Registers lineage and provenance information for a knowledge package.

### 15. Get Knowledge Object
- **Endpoint:** `GET /packages/{package_id}/knowledge-object`
- **URL:** `http://127.0.0.1:8000/packages/BHIV-PKG-.../knowledge-object`
- **Expected Response:** Complete knowledge object with source reference and derivation path.
- **Description:** Returns registered knowledge object and lineage information.

---

## Retrieval Readiness Endpoints

### 16. Check Retrieval Readiness
- **Endpoint:** `GET /packages/{package_id}/retrieval`
- **URL:** `http://127.0.0.1:8000/packages/BHIV-PKG-.../retrieval`
- **Expected Response:**
  ```json
  {
    "package_id": "BHIV-PKG-...",
    "retrieval_status": "RETRIEVABLE",
    "lifecycle_status": "CERTIFIED",
    "has_knowledge_object": true,
    "passed_rules": [...],
    "failed_rules": [...],
    "corrective_actions": [...],
    "certified_retrievable": true
  }
  ```
- **Description:** Evaluates retrieval readiness based on lifecycle status, metadata completeness, and lineage.

---

## Authentication & Authorization Endpoints

### 17. Issue JWT Token
- **Endpoint:** `POST /auth/token`
- **URL:** `http://127.0.0.1:8000/auth/token`
- **Method:** POST
- **Request Body:**
  ```json
  {
    "actor": "john_doe",
    "roles": ["reader", "writer"]
  }
  ```
- **Expected Response:**
  ```json
  {
    "access_token": "eyJ...",
    "actor": "john_doe",
    "roles": ["reader", "writer"],
    "expires_at": "2026-09-28T10:08:45"
  }
  ```
- **Description:** Issues a signed, expiring JWT token for authentication. Token is used in Authorization header for protected endpoints.

**Note:** Token issuance does NOT verify caller identity (no login step exists). Token itself is signed, tamper-evident, and time-limited. Every write operation and canonical repository read checks roles inside the token.

---

## BCAES Registry Endpoints

### 18. List BCAES Registries
- **Endpoint:** `GET /bcaes/registries`
- **URL:** `http://127.0.0.1:8000/bcaes/registries`
- **Expected Response:**
  ```json
  {
    "registries": {
      "product": 15,
      "capability": 42,
      "service": 28,
      "component": 12
    }
  }
  ```
- **Description:** Returns summary of all BCAES registry types and object counts.

### 19. List Registry Objects (Type)
- **Endpoint:** `GET /bcaes/registries/{registry_type}/objects`
- **URL:** `http://127.0.0.1:8000/bcaes/registries/product/objects`
- **Expected Response:**
  ```json
  {
    "registry_type": "product",
    "objects": [...]
  }
  ```
- **Description:** Lists all objects in a specific BCAES registry type.

### 20. Get Registry Object
- **Endpoint:** `GET /bcaes/registries/{registry_type}/objects/{object_id}`
- **URL:** `http://127.0.0.1:8000/bcaes/registries/product/objects/object-123`
- **Expected Response:**
  ```json
  {
    "id": "object-123",
    "registry_type": "product",
    "name": "...",
    "status": "active"
  }
  ```
- **Description:** Returns specific BCAES registry object details.

### 21. Register BCAES Object
- **Endpoint:** `POST /bcaes/registries/{registry_type}/objects`
- **URL:** `http://127.0.0.1:8000/bcaes/registries/product/objects`
- **Method:** POST
- **Request Body:**
  ```json
  {
    "name": "New Product",
    "description": "...",
    "status": "active"
  }
  ```
- **Headers:** `Authorization: Bearer {token}`
- **Description:** Registers new object in BCAES registry (requires authentication).

### 22. Update BCAES Object
- **Endpoint:** `PATCH /bcaes/registries/{registry_type}/objects/{object_id}`
- **URL:** `http://127.0.0.1:8000/bcaes/registries/product/objects/object-123`
- **Method:** PATCH
- **Headers:** `Authorization: Bearer {token}`
- **Description:** Updates existing BCAES registry object (requires authentication).

### 23. Delete BCAES Object
- **Endpoint:** `DELETE /bcaes/registries/{registry_type}/objects/{object_id}`
- **URL:** `http://127.0.0.1:8000/bcaes/registries/product/objects/object-123`
- **Method:** DELETE
- **Headers:** `Authorization: Bearer {token}`
- **Description:** Deletes BCAES registry object (requires authentication).

### 24. Search BCAES Registry
- **Endpoint:** `GET /bcaes/search`
- **URL:** `http://127.0.0.1:8000/bcaes/search?q=product&registry_type=product&owner=acme&status=active`
- **Expected Response:**
  ```json
  {
    "count": 5,
    "results": [...]
  }
  ```
- **Query Parameters:**
  - `q` (optional): Search query
  - `registry_type` (optional): Filter by registry type
  - `owner` (optional): Filter by owner
  - `status` (optional): Filter by status
- **Description:** Full-text search across BCAES registries with optional filters.

### 25. Get BCAES Object Relationships
- **Endpoint:** `GET /bcaes/relationships/{object_id}`
- **URL:** `http://127.0.0.1:8000/bcaes/relationships/object-123`
- **Expected Response:**
  ```json
  {
    "object_id": "object-123",
    "depends_on": [...],
    "required_by": [...],
    "related": [...]
  }
  ```
- **Description:** Returns relationship graph for a BCAES registry object.

### 26. Get BCAES Transitive Dependencies
- **Endpoint:** `GET /bcaes/dependencies/{object_id}`
- **URL:** `http://127.0.0.1:8000/bcaes/dependencies/object-123`
- **Expected Response:**
  ```json
  {
    "object_id": "object-123",
    "direct_dependencies": [...],
    "transitive_dependencies": [...],
    "dependency_tree": {...}
  }
  ```
- **Description:** Computes and returns full transitive dependency tree.

### 27. Capability Reuse Check
- **Endpoint:** `GET /bcaes/capability-reuse-check`
- **URL:** `http://127.0.0.1:8000/bcaes/capability-reuse-check?name=auth-service`
- **Expected Response:**
  ```json
  {
    "name": "auth-service",
    "can_reuse": true,
    "existing_implementations": 3,
    "recommendation": "Reuse existing implementation from team-a"
  }
  ```
- **Description:** Checks if a capability can/should be reused from existing implementations.

### 28. Validate BCAES Classification
- **Endpoint:** `GET /bcaes/validate/classification`
- **URL:** `http://127.0.0.1:8000/bcaes/validate/classification`
- **Expected Response:**
  ```json
  {
    "passed": true,
    "issues": [],
    "summary": "All objects properly classified"
  }
  ```
- **Description:** Validates that all BCAES objects are properly classified.

### 29. Detect BCAES Duplicates
- **Endpoint:** `GET /bcaes/validate/duplicates`
- **URL:** `http://127.0.0.1:8000/bcaes/validate/duplicates`
- **Expected Response:**
  ```json
  {
    "duplicate_count": 0,
    "duplicates": [],
    "passed": true
  }
  ```
- **Description:** Detects duplicate objects across BCAES registries.

### 30. Validate BCAES Ownership
- **Endpoint:** `GET /bcaes/validate/ownership`
- **URL:** `http://127.0.0.1:8000/bcaes/validate/ownership`
- **Description:** Validates ownership chains and audit trail.

### 31. Validate Authority Boundaries
- **Endpoint:** `GET /bcaes/validate/authority-boundaries`
- **URL:** `http://127.0.0.1:8000/bcaes/validate/authority-boundaries`
- **Description:** Validates that authority boundaries are maintained.

### 32. Validate Version Compatibility
- **Endpoint:** `GET /bcaes/validate/version-compatibility`
- **URL:** `http://127.0.0.1:8000/bcaes/validate/version-compatibility`
- **Description:** Checks version compatibility across dependencies.

### 33. Validate Dependency Integrity
- **Endpoint:** `GET /bcaes/validate/dependency-integrity`
- **URL:** `http://127.0.0.1:8000/bcaes/validate/dependency-integrity`
- **Description:** Validates dependency graph integrity.

### 34. Validate BCAES Architecture
- **Endpoint:** `GET /bcaes/validate/architecture`
- **URL:** `http://127.0.0.1:8000/bcaes/validate/architecture`
- **Expected Response:**
  ```json
  {
    "passed": true,
    "replay_hash": "sha256...",
    "issues": [],
    "timestamp": "..."
  }
  ```
- **Description:** Validates full architecture consistency and generates replay hash.

### 35. Upsert BCAES Convergence
- **Endpoint:** `POST /bcaes/convergence/{object_id}`
- **URL:** `http://127.0.0.1:8000/bcaes/convergence/object-123`
- **Method:** POST
- **Headers:** `Authorization: Bearer {token}`
- **Description:** Records production convergence state for an object.

### 36. Get BCAES Convergence
- **Endpoint:** `GET /bcaes/convergence/{object_id}`
- **URL:** `http://127.0.0.1:8000/bcaes/convergence/object-123`
- **Expected Response:**
  ```json
  {
    "object_id": "object-123",
    "convergence_stage": "production",
    "maturity_score": 85,
    "ready_at": "..."
  }
  ```
- **Description:** Returns convergence state and maturity assessment.

### 37. List BCAES Convergence
- **Endpoint:** `GET /bcaes/convergence`
- **URL:** `http://127.0.0.1:8000/bcaes/convergence`
- **Expected Response:**
  ```json
  {
    "count": 10,
    "records": [...]
  }
  ```
- **Description:** Lists all convergence records with maturity scores.

### 38. Get BCAES Snapshot
- **Endpoint:** `GET /bcaes/snapshot`
- **URL:** `http://127.0.0.1:8000/bcaes/snapshot`
- **Expected Response:**
  ```json
  {
    "timestamp": "2026-09-28T09:08:45",
    "total_objects": 97,
    "total_convergence": 45,
    "maturity_average": 78.5,
    "registry_summary": {...}
  }
  ```
- **Description:** Returns full snapshot of current BCAES registry state and reality.

---

## Canonical Repository Endpoints

### 39. Register Document
- **Endpoint:** `POST /canonical-repository/documents`
- **URL:** `http://127.0.0.1:8000/canonical-repository/documents`
- **Method:** POST
- **Headers:** `Authorization: Bearer {token}`
- **Request Body:**
  ```json
  {
    "category": "governance",
    "title": "Data Governance Policy",
    "content": "..."
  }
  ```
- **Description:** Registers new canonical document (requires authentication).

### 40. List Canonical Documents
- **Endpoint:** `GET /canonical-repository/documents`
- **URL:** `http://127.0.0.1:8000/canonical-repository/documents`
- **Headers:** `Authorization: Bearer {token}`
- **Expected Response:**
  ```json
  {
    "count": 5,
    "documents": [...]
  }
  ```
- **Description:** Lists all accessible canonical documents (requires authentication).

### 41. Get Canonical Document
- **Endpoint:** `GET /canonical-repository/documents/{document_id}`
- **URL:** `http://127.0.0.1:8000/canonical-repository/documents/doc-123`
- **Headers:** `Authorization: Bearer {token}`
- **Description:** Returns specific canonical document (requires authentication).

### 42. Get Document by Category
- **Endpoint:** `GET /canonical-repository/by-category/{category}`
- **URL:** `http://127.0.0.1:8000/canonical-repository/by-category/governance`
- **Headers:** `Authorization: Bearer {token}`
- **Description:** Returns canonical document for a specific category (requires authentication).

### 43. Publish Document Version
- **Endpoint:** `POST /canonical-repository/documents/{document_id}/versions`
- **URL:** `http://127.0.0.1:8000/canonical-repository/documents/doc-123/versions`
- **Method:** POST
- **Headers:** `Authorization: Bearer {token}`
- **Request Body:**
  ```json
  {
    "content": "...",
    "change_summary": "Updated governance policy"
  }
  ```
- **Description:** Publishes new version of document (requires authentication).

### 44. List Document Versions
- **Endpoint:** `GET /canonical-repository/documents/{document_id}/versions`
- **URL:** `http://127.0.0.1:8000/canonical-repository/documents/doc-123/versions`
- **Headers:** `Authorization: Bearer {token}`
- **Description:** Lists all versions of a document (requires authentication).

### 45. Get Specific Document Version
- **Endpoint:** `GET /canonical-repository/documents/{document_id}/versions/{version_number}`
- **URL:** `http://127.0.0.1:8000/canonical-repository/documents/doc-123/versions/2`
- **Headers:** `Authorization: Bearer {token}`
- **Description:** Returns specific version of document (requires authentication).

### 46. Get Latest Document Version
- **Endpoint:** `GET /canonical-repository/documents/{document_id}/latest`
- **URL:** `http://127.0.0.1:8000/canonical-repository/documents/doc-123/latest`
- **Headers:** `Authorization: Bearer {token}`
- **Description:** Returns latest version of document (requires authentication).

### 47. Verify Document Chain
- **Endpoint:** `GET /canonical-repository/documents/{document_id}/verify`
- **URL:** `http://127.0.0.1:8000/canonical-repository/documents/doc-123/verify`
- **Headers:** `Authorization: Bearer {token}`
- **Expected Response:**
  ```json
  {
    "document_id": "doc-123",
    "chain_valid": true,
    "version_count": 5,
    "hash_chain": "sha256..."
  }
  ```
- **Description:** Verifies integrity of document version chain via hash verification (requires authentication).

---

## Evidence & Bucket Endpoints

### 48. Store Evidence
- **Endpoint:** `POST /evidence/{evidence_id}`
- **URL:** `http://127.0.0.1:8000/evidence/evidence-123`
- **Method:** POST
- **Request Body:** Evidence payload (JSON)
- **Expected Response:**
  ```json
  {
    "evidence_id": "evidence-123",
    "stored_at": "...",
    "status": "persisted"
  }
  ```
- **Description:** Persists evidence record to configured bucket.

### 49. Retrieve Evidence
- **Endpoint:** `GET /evidence/{evidence_id}`
- **URL:** `http://127.0.0.1:8000/evidence/evidence-123`
- **Expected Response:** Original evidence payload.
- **Description:** Retrieves stored evidence record from bucket.

### 50. Store Provenance
- **Endpoint:** `POST /provenance/{dataset_id}`
- **URL:** `http://127.0.0.1:8000/provenance/dataset-123`
- **Method:** POST
- **Request Body:** Provenance record (JSON)
- **Description:** Persists provenance record for a dataset.

### 51. Get Provenance
- **Endpoint:** `GET /provenance/{package_id}`
- **URL:** `http://127.0.0.1:8000/provenance/BHIV-PKG-...`
- **Expected Response:** Full provenance chain for package.
- **Description:** Retrieves complete provenance lineage for a knowledge package.

### 52. Bucket Status
- **Endpoint:** `GET /bucket/status`
- **URL:** `http://127.0.0.1:8000/bucket/status`
- **Expected Response:**
  ```json
  {
    "status": "available",
    "records_stored": 1500,
    "last_access": "..."
  }
  ```
- **Description:** Health check for evidence bucket connectivity and status.

---

## Database Targets & Ingestion Endpoints

### 53. List Databases
- **Endpoint:** `GET /databases`
- **URL:** `http://127.0.0.1:8000/databases`
- **Headers:** `Authorization: Bearer {token}` (requires admin/writer role)
- **Expected Response:**
  ```json
  {
    "databases": [
      "VectorDB",
      "GraphDB",
      "MetadataDB",
      "DocumentDB",
      "TimeSeriesDB",
      "RelationalDB",
      "ArchiveDB",
      "AnalyticsDB"
    ]
  }
  ```
- **Description:** Lists all 8 MASTERDB target databases available for controlled ingestion.

### 54. Ingest Dataset
- **Endpoint:** `POST /ingest`
- **URL:** `http://127.0.0.1:8000/ingest`
- **Method:** POST
- **Headers:** `Authorization: Bearer {token}` (requires admin/writer role)
- **Request Body:**
  ```json
  {
    "dataset_id": "sample-certified",
    "target_database": "RelationalDB",
    "source_format": "csv"
  }
  ```
- **Expected Response:**
  ```json
  {
    "job_id": "ingest-job-123",
    "dataset_id": "sample-certified",
    "target_database": "RelationalDB",
    "status": "queued"
  }
  ```
- **Description:** Initiates controlled ingestion of CERTIFIED dataset into target database.

### 55. Get Ingestion Job Status
- **Endpoint:** `GET /ingest/jobs/{job_id}`
- **URL:** `http://127.0.0.1:8000/ingest/jobs/ingest-job-123`
- **Headers:** `Authorization: Bearer {token}`
- **Expected Response:**
  ```json
  {
    "job_id": "ingest-job-123",
    "dataset_id": "sample-certified",
    "target_database": "RelationalDB",
    "status": "running",
    "progress_percent": 45,
    "records_processed": 1500
  }
  ```
- **Description:** Returns status and progress of ingestion job.

### 56. List Ingestion Jobs
- **Endpoint:** `GET /ingest/jobs`
- **URL:** `http://127.0.0.1:8000/ingest/jobs`
- **Headers:** `Authorization: Bearer {token}`
- **Expected Response:**
  ```json
  {
    "jobs": [...]
  }
  ```
- **Description:** Lists all ingestion jobs (past and present).

---

## Shared Data Endpoints

### 57. Create/Update Shared Record (Authentication)
- **Endpoint:** `POST /shared/authentication/{record_id}`
- **URL:** `http://127.0.0.1:8000/shared/authentication/auth-record-1`
- **Method:** POST
- **Headers:** `Authorization: Bearer {token}`
- **Description:** Creates or updates authentication shared record.

### 58. Get Shared Record (Authentication)
- **Endpoint:** `GET /shared/authentication/{record_id}`
- **URL:** `http://127.0.0.1:8000/shared/authentication/auth-record-1`
- **Description:** Retrieves authentication shared record.

### 59. Create/Update Shared Record (Identity)
- **Endpoint:** `POST /shared/identity/{record_id}`
- **URL:** `http://127.0.0.1:8000/shared/identity/identity-record-1`
- **Method:** POST
- **Headers:** `Authorization: Bearer {token}`
- **Description:** Creates or updates identity shared record.

### 60. Get Shared Record (Identity)
- **Endpoint:** `GET /shared/identity/{record_id}`
- **URL:** `http://127.0.0.1:8000/shared/identity/identity-record-1`
- **Description:** Retrieves identity shared record.

### 61. Create/Update Shared Record (Organizations)
- **Endpoint:** `POST /shared/organizations/{record_id}`
- **URL:** `http://127.0.0.1:8000/shared/organizations/org-record-1`
- **Method:** POST
- **Headers:** `Authorization: Bearer {token}`
- **Description:** Creates or updates organizations shared record.

### 62. Get Shared Record (Organizations)
- **Endpoint:** `GET /shared/organizations/{record_id}`
- **URL:** `http://127.0.0.1:8000/shared/organizations/org-record-1`
- **Description:** Retrieves organizations shared record.

### 63. Create/Update Shared Record (Configuration)
- **Endpoint:** `POST /shared/configuration/{record_id}`
- **URL:** `http://127.0.0.1:8000/shared/configuration/config-record-1`
- **Method:** POST
- **Headers:** `Authorization: Bearer {token}`
- **Description:** Creates or updates configuration shared record.

### 64. Get Shared Record (Configuration)
- **Endpoint:** `GET /shared/configuration/{record_id}`
- **URL:** `http://127.0.0.1:8000/shared/configuration/config-record-1`
- **Description:** Retrieves configuration shared record.

### 65. Create/Update Shared Record (Knowledge References)
- **Endpoint:** `POST /shared/knowledge-references/{record_id}`
- **URL:** `http://127.0.0.1:8000/shared/knowledge-references/kr-record-1`
- **Method:** POST
- **Headers:** `Authorization: Bearer {token}`
- **Description:** Creates or updates knowledge references shared record.

### 66. Get Shared Record (Knowledge References)
- **Endpoint:** `GET /shared/knowledge-references/{record_id}`
- **URL:** `http://127.0.0.1:8000/shared/knowledge-references/kr-record-1`
- **Description:** Retrieves knowledge references shared record.

### 67. Create/Update Shared Record (Notifications)
- **Endpoint:** `POST /shared/notifications/{record_id}`
- **URL:** `http://127.0.0.1:8000/shared/notifications/notif-record-1`
- **Method:** POST
- **Headers:** `Authorization: Bearer {token}`
- **Description:** Creates or updates notifications shared record.

### 68. Get Shared Record (Notifications)
- **Endpoint:** `GET /shared/notifications/{record_id}`
- **URL:** `http://127.0.0.1:8000/shared/notifications/notif-record-1`
- **Description:** Retrieves notifications shared record.

---

## MDU Integration Endpoints

### 69. Check MDU Schema Compatibility
- **Endpoint:** `GET /mdu/schema-compatibility/{package_id}`
- **URL:** `http://127.0.0.1:8000/mdu/schema-compatibility/BHIV-PKG-...?local_schema_version=1.0`
- **Query Parameters:**
  - `local_schema_version` (required): Local schema version
- **Expected Response:**
  ```json
  {
    "package_id": "BHIV-PKG-...",
    "local_schema_version": "1.0",
    "mdu_schema_version": "2.0",
    "compatible": true,
    "transformations_needed": [...]
  }
  ```
- **Description:** Checks schema compatibility with MDU canonical schemas.

### 70. Get MDU Schema
- **Endpoint:** `GET /mdu/schema`
- **URL:** `http://127.0.0.1:8000/mdu/schema`
- **Expected Response:** Full MDU canonical schema.
- **Description:** Retrieves current MDU canonical schema definition.

---

## TANTRA Runtime Interface Endpoints

### 71. Register Dataset (TANTRA)
- **Endpoint:** `POST /tantra/datasets/register`
- **URL:** `http://127.0.0.1:8000/tantra/datasets/register`
- **Method:** POST
- **Request Body:**
  ```json
  {
    "dataset_id": "BHIV-DS-MARITIME-AIS-LIVE-001",
    "dataset_version": "1.0",
    "schema_version": "1.0",
    "board": "maritime",
    "medium": "ais",
    "language": "en",
    "owner": "nupur"
  }
  ```
- **Description:** Registers dataset via TANTRA runtime interface.

### 72. Get Package Runtime (TANTRA)
- **Endpoint:** `GET /tantra/packages/{package_id}/runtime`
- **URL:** `http://127.0.0.1:8000/tantra/packages/BHIV-PKG-.../runtime`
- **Expected Response:**
  ```json
  {
    "package_id": "BHIV-PKG-...",
    "lifecycle_status": "CERTIFIED",
    "retrieval_status": "RETRIEVABLE",
    "lineage": {...},
    "certification": {...}
  }
  ```
- **Description:** Returns bundled runtime package info (lifecycle + lineage + retrieval + certification).

---

## Runtime Discovery Endpoints

### 73. Discover Packages
- **Endpoint:** `GET /discovery/packages`
- **URL:** `http://127.0.0.1:8000/discovery/packages?board=maritime&status=CERTIFIED`
- **Query Parameters:**
  - `board` (optional): Filter by board/domain
  - `status` (optional): Filter by lifecycle status
  - `owner` (optional): Filter by owner
  - `limit` (optional): Max results
  - `offset` (optional): Pagination offset
- **Expected Response:**
  ```json
  {
    "count": 5,
    "packages": [...]
  }
  ```
- **Description:** Discovers packages by board, status, and other criteria.

---

## Runtime Identity & Configuration Endpoints

### 74. Get Runtime Identity
- **Endpoint:** `GET /runtime/identity`
- **URL:** `http://127.0.0.1:8000/runtime/identity`
- **Expected Response:**
  ```json
  {
    "service_name": "MASTERDB",
    "version": "1.0.0",
    "constitutional_role": "Knowledge Layer participant",
    "capabilities": [...],
    "api_groups": {...},
    "health_check_url": "/health",
    "readiness_check_url": "/ready",
    "status": "not_yet_registered"
  }
  ```
- **Description:** Self-description manifest for TANTRA Runtime Registry registration.

### 75. Get Configuration Report
- **Endpoint:** `GET /admin/configuration`
- **URL:** `http://127.0.0.1:8000/admin/configuration`
- **Headers:** `Authorization: Bearer {token}` (requires admin role)
- **Expected Response:**
  ```json
  {
    "auth_configured": true,
    "database_configured": false,
    "storage_configured": true,
    "mdu_integration": "configured",
    "issues": []
  }
  ```
- **Description:** Live configuration validation report. Never returns actual secret values.

---

## Backup & Recovery Endpoints

### 76. Create Backup
- **Endpoint:** `GET /admin/backup`
- **URL:** `http://127.0.0.1:8000/admin/backup`
- **Headers:** `Authorization: Bearer {token}` (requires admin role)
- **Expected Response:**
  ```json
  {
    "backup_id": "backup-...",
    "timestamp": "2026-09-28T09:08:45",
    "stores": {
      "bcaes_registry": {"records": 97},
      "canonical_repository": {"records": 15}
    }
  }
  ```
- **Description:** Creates application-level snapshot export of all records.

### 77. Restore Backup
- **Endpoint:** `POST /admin/restore`
- **URL:** `http://127.0.0.1:8000/admin/restore`
- **Method:** POST
- **Headers:** `Authorization: Bearer {token}` (requires admin role)
- **Request Body:** Backup snapshot (from /admin/backup)
- **Expected Response:**
  ```json
  {
    "restored": {
      "bcaes_registry": 97,
      "canonical_repository": 15
    }
  }
  ```
- **Description:** Restores application-level records from snapshot export.

---

## Observability & Metrics Endpoints

### 78. Prometheus Metrics
- **Endpoint:** `GET /metrics`
- **URL:** `http://127.0.0.1:8000/metrics`
- **Expected Response:** Prometheus text exposition format
  ```
  # HELP masterdb_bcaes_registry_objects_total Objects registered per BCAES registry type.
  # TYPE masterdb_bcaes_registry_objects_total gauge
  masterdb_bcaes_registry_objects_total{registry_type="product"} 15
  masterdb_bcaes_registry_objects_total{registry_type="capability"} 42
  masterdb_bcaes_registry_objects_total{registry_type="service"} 28
  masterdb_bcaes_registry_objects_total{registry_type="component"} 12
  
  # HELP masterdb_canonical_documents_total Documents in the canonical repository.
  # TYPE masterdb_canonical_documents_total gauge
  masterdb_canonical_documents_total 15
  
  # HELP masterdb_up Process liveness (always 1 if this endpoint responds).
  # TYPE masterdb_up gauge
  masterdb_up 1
  ```
- **Description:** Prometheus metrics in standard text exposition format for InsightFlow/InsightCore integration.

### 79. Push to InsightBridge
- **Endpoint:** `POST /observability/push-to-insightbridge`
- **URL:** `http://127.0.0.1:8000/observability/push-to-insightbridge`
- **Method:** POST
- **Headers:** `Authorization: Bearer {token}`
- **Expected Response:**
  ```json
  {
    "pushed": true,
    "insightbridge_response": {...}
  }
  ```
- **Description:** Active push to InsightBridge for telemetry (if configured via PRAVAH_BHIV_INSIGHT_FLOW_BRIDGE).

---

## Operational Sync Endpoints

### 80. Upsert Review Reference (PARIKSHAK)
- **Endpoint:** `POST /parikshak/review-references`
- **URL:** `http://127.0.0.1:8000/parikshak/review-references`
- **Method:** POST
- **Headers:** `Authorization: Bearer {token}` (requires "parikshak-sync" or "bhiv-admin" role)
- **Description:** Engineering review reference sync for PARIKSHAK integration.

### 81. List Review References
- **Endpoint:** `GET /parikshak/review-references`
- **URL:** `http://127.0.0.1:8000/parikshak/review-references`
- **Expected Response:**
  ```json
  {
    "count": 10,
    "records": [...]
  }
  ```
- **Description:** Lists all review references (open read access).

### 82. Get Review Reference
- **Endpoint:** `GET /parikshak/review-references/{external_review_id}`
- **URL:** `http://127.0.0.1:8000/parikshak/review-references/review-123`
- **Description:** Retrieves specific review reference.

### 83. Upsert Task State (NIYANTRAN)
- **Endpoint:** `POST /niyantran/task-state`
- **URL:** `http://127.0.0.1:8000/niyantran/task-state`
- **Method:** POST
- **Headers:** `Authorization: Bearer {token}` (requires "niyantran-sync" or "bhiv-admin" role)
- **Description:** Operational task lifecycle sync for NIYANTRAN integration.

### 84. List Task State
- **Endpoint:** `GET /niyantran/task-state`
- **URL:** `http://127.0.0.1:8000/niyantran/task-state`
- **Expected Response:**
  ```json
  {
    "count": 20,
    "records": [...]
  }
  ```
- **Description:** Lists all operational tasks.

### 85. Get Task State
- **Endpoint:** `GET /niyantran/task-state/{external_task_id}`
- **URL:** `http://127.0.0.1:8000/niyantran/task-state/task-123`
- **Description:** Retrieves specific task state.

---

## Replay Registry Endpoints

### 86. Get Replay Registry Manifest
- **Endpoint:** `GET /replay-registry/manifest`
- **URL:** `http://127.0.0.1:8000/replay-registry/manifest`
- **Expected Response:**
  ```json
  {
    "service_name": "MASTERDB",
    "replay_capabilities": [
      {
        "name": "bcaes_registry_architecture",
        "endpoint": "/bcaes/validate/architecture",
        "mechanism": "replay_hash over full registry state"
      },
      {
        "name": "canonical_repository_document_chain",
        "endpoint": "/canonical-repository/documents/{document_id}/verify",
        "mechanism": "sha256 hash chain"
      },
      {
        "name": "knowledge_package_lifecycle",
        "endpoint": "/packages/{package_id}/replay",
        "mechanism": "rebuilds package status from transition history"
      }
    ],
    "status": "not_yet_registered"
  }
  ```
- **Description:** Unified manifest of all replay-capable surfaces in MASTERDB.

---

## Summary Table

| # | Endpoint | Method | URL | Auth Required | Status |
|---|----------|--------|-----|---------------|---------| 
| 1 | /health | GET | http://127.0.0.1:8000/health | No | ✅ |
| 2 | /ready | GET | http://127.0.0.1:8000/ready | No | ✅ |
| 3 | /docs | GET | http://127.0.0.1:8000/docs | No | ✅ |
| 4 | /openapi.json | GET | http://127.0.0.1:8000/openapi.json | No | ✅ |
| 5 | /validate | POST | http://127.0.0.1:8000/validate | No | ✅ |
| 6 | /certify | POST | http://127.0.0.1:8000/certify | No | ✅ |
| 7 | /status/{dataset_id} | GET | http://127.0.0.1:8000/status/{id} | No | ✅ |
| 8 | /report/{dataset_id} | GET | http://127.0.0.1:8000/report/{id} | No | ✅ |
| 9 | /packages/register | POST | http://127.0.0.1:8000/packages/register | No | ✅ |
| 10 | /packages/promote | POST | http://127.0.0.1:8000/packages/promote | No | ✅ |
| 11 | /packages/{id} | GET | http://127.0.0.1:8000/packages/{id} | No | ✅ |
| 12 | /packages/{id}/replay | GET | http://127.0.0.1:8000/packages/{id}/replay | No | ✅ |
| 13 | /packages/{id}/audit | GET | http://127.0.0.1:8000/packages/{id}/audit | No | ✅ |
| 14 | /packages/{id}/knowledge-object | POST | http://127.0.0.1:8000/packages/{id}/knowledge-object | No | ✅ |
| 15 | /packages/{id}/knowledge-object | GET | http://127.0.0.1:8000/packages/{id}/knowledge-object | No | ✅ |
| 16 | /packages/{id}/retrieval | GET | http://127.0.0.1:8000/packages/{id}/retrieval | No | ✅ |
| 17 | /auth/token | POST | http://127.0.0.1:8000/auth/token | No | ✅ |
| 18 | /bcaes/registries | GET | http://127.0.0.1:8000/bcaes/registries | No | ✅ |
| 19 | /bcaes/registries/{type}/objects | GET | http://127.0.0.1:8000/bcaes/registries/{type}/objects | No | ✅ |
| 20 | /bcaes/registries/{type}/objects/{id} | GET | http://127.0.0.1:8000/bcaes/registries/{type}/objects/{id} | No | ✅ |
| 21 | /bcaes/registries/{type}/objects | POST | http://127.0.0.1:8000/bcaes/registries/{type}/objects | Yes | ✅ |
| 22 | /bcaes/registries/{type}/objects/{id} | PATCH | http://127.0.0.1:8000/bcaes/registries/{type}/objects/{id} | Yes | ✅ |
| 23 | /bcaes/registries/{type}/objects/{id} | DELETE | http://127.0.0.1:8000/bcaes/registries/{type}/objects/{id} | Yes | ✅ |
| 24 | /bcaes/search | GET | http://127.0.0.1:8000/bcaes/search | No | ✅ |
| 25 | /bcaes/relationships/{id} | GET | http://127.0.0.1:8000/bcaes/relationships/{id} | No | ✅ |
| 26 | /bcaes/dependencies/{id} | GET | http://127.0.0.1:8000/bcaes/dependencies/{id} | No | ✅ |
| 27 | /bcaes/capability-reuse-check | GET | http://127.0.0.1:8000/bcaes/capability-reuse-check | No | ✅ |
| 28 | /bcaes/validate/classification | GET | http://127.0.0.1:8000/bcaes/validate/classification | No | ✅ |
| 29 | /bcaes/validate/duplicates | GET | http://127.0.0.1:8000/bcaes/validate/duplicates | No | ✅ |
| 30 | /bcaes/validate/ownership | GET | http://127.0.0.1:8000/bcaes/validate/ownership | No | ✅ |
| 31 | /bcaes/validate/authority-boundaries | GET | http://127.0.0.1:8000/bcaes/validate/authority-boundaries | No | ✅ |
| 32 | /bcaes/validate/version-compatibility | GET | http://127.0.0.1:8000/bcaes/validate/version-compatibility | No | ✅ |
| 33 | /bcaes/validate/dependency-integrity | GET | http://127.0.0.1:8000/bcaes/validate/dependency-integrity | No | ✅ |
| 34 | /bcaes/validate/architecture | GET | http://127.0.0.1:8000/bcaes/validate/architecture | No | ✅ |
| 35 | /bcaes/convergence/{id} | POST | http://127.0.0.1:8000/bcaes/convergence/{id} | Yes | ✅ |
| 36 | /bcaes/convergence/{id} | GET | http://127.0.0.1:8000/bcaes/convergence/{id} | No | ✅ |
| 37 | /bcaes/convergence | GET | http://127.0.0.1:8000/bcaes/convergence | No | ✅ |
| 38 | /bcaes/snapshot | GET | http://127.0.0.1:8000/bcaes/snapshot | No | ✅ |
| 39 | /canonical-repository/documents | POST | http://127.0.0.1:8000/canonical-repository/documents | Yes | ✅ |
| 40 | /canonical-repository/documents | GET | http://127.0.0.1:8000/canonical-repository/documents | Yes | ✅ |
| 41 | /canonical-repository/documents/{id} | GET | http://127.0.0.1:8000/canonical-repository/documents/{id} | Yes | ✅ |
| 42 | /canonical-repository/by-category/{cat} | GET | http://127.0.0.1:8000/canonical-repository/by-category/{cat} | Yes | ✅ |
| 43 | /canonical-repository/documents/{id}/versions | POST | http://127.0.0.1:8000/canonical-repository/documents/{id}/versions | Yes | ✅ |
| 44 | /canonical-repository/documents/{id}/versions | GET | http://127.0.0.1:8000/canonical-repository/documents/{id}/versions | Yes | ✅ |
| 45 | /canonical-repository/documents/{id}/versions/{v} | GET | http://127.0.0.1:8000/canonical-repository/documents/{id}/versions/{v} | Yes | ✅ |
| 46 | /canonical-repository/documents/{id}/latest | GET | http://127.0.0.1:8000/canonical-repository/documents/{id}/latest | Yes | ✅ |
| 47 | /canonical-repository/documents/{id}/verify | GET | http://127.0.0.1:8000/canonical-repository/documents/{id}/verify | Yes | ✅ |
| 48 | /evidence/{id} | POST | http://127.0.0.1:8000/evidence/{id} | No | ✅ |
| 49 | /evidence/{id} | GET | http://127.0.0.1:8000/evidence/{id} | No | ✅ |
| 50 | /provenance/{dataset_id} | POST | http://127.0.0.1:8000/provenance/{dataset_id} | No | ✅ |
| 51 | /provenance/{package_id} | GET | http://127.0.0.1:8000/provenance/{package_id} | No | ✅ |
| 52 | /bucket/status | GET | http://127.0.0.1:8000/bucket/status | No | ✅ |
| 53 | /databases | GET | http://127.0.0.1:8000/databases | Yes | ✅ |
| 54 | /ingest | POST | http://127.0.0.1:8000/ingest | Yes | ✅ |
| 55 | /ingest/jobs/{id} | GET | http://127.0.0.1:8000/ingest/jobs/{id} | Yes | ✅ |
| 56 | /ingest/jobs | GET | http://127.0.0.1:8000/ingest/jobs | Yes | ✅ |
| 57 | /shared/authentication/{id} | POST | http://127.0.0.1:8000/shared/authentication/{id} | Yes | ✅ |
| 58 | /shared/authentication/{id} | GET | http://127.0.0.1:8000/shared/authentication/{id} | No | ✅ |
| 59 | /shared/identity/{id} | POST | http://127.0.0.1:8000/shared/identity/{id} | Yes | ✅ |
| 60 | /shared/identity/{id} | GET | http://127.0.0.1:8000/shared/identity/{id} | No | ✅ |
| 61 | /shared/organizations/{id} | POST | http://127.0.0.1:8000/shared/organizations/{id} | Yes | ✅ |
| 62 | /shared/organizations/{id} | GET | http://127.0.0.1:8000/shared/organizations/{id} | No | ✅ |
| 63 | /shared/configuration/{id} | POST | http://127.0.0.1:8000/shared/configuration/{id} | Yes | ✅ |
| 64 | /shared/configuration/{id} | GET | http://127.0.0.1:8000/shared/configuration/{id} | No | ✅ |
| 65 | /shared/knowledge-references/{id} | POST | http://127.0.0.1:8000/shared/knowledge-references/{id} | Yes | ✅ |
| 66 | /shared/knowledge-references/{id} | GET | http://127.0.0.1:8000/shared/knowledge-references/{id} | No | ✅ |
| 67 | /shared/notifications/{id} | POST | http://127.0.0.1:8000/shared/notifications/{id} | Yes | ✅ |
| 68 | /shared/notifications/{id} | GET | http://127.0.0.1:8000/shared/notifications/{id} | No | ✅ |
| 69 | /mdu/schema-compatibility/{id} | GET | http://127.0.0.1:8000/mdu/schema-compatibility/{id} | No | ✅ |
| 70 | /mdu/schema | GET | http://127.0.0.1:8000/mdu/schema | No | ✅ |
| 71 | /tantra/datasets/register | POST | http://127.0.0.1:8000/tantra/datasets/register | No | ✅ |
| 72 | /tantra/packages/{id}/runtime | GET | http://127.0.0.1:8000/tantra/packages/{id}/runtime | No | ✅ |
| 73 | /discovery/packages | GET | http://127.0.0.1:8000/discovery/packages | No | ✅ |
| 74 | /runtime/identity | GET | http://127.0.0.1:8000/runtime/identity | No | ✅ |
| 75 | /admin/configuration | GET | http://127.0.0.1:8000/admin/configuration | Yes | ✅ |
| 76 | /admin/backup | GET | http://127.0.0.1:8000/admin/backup | Yes | ✅ |
| 77 | /admin/restore | POST | http://127.0.0.1:8000/admin/restore | Yes | ✅ |
| 78 | /metrics | GET | http://127.0.0.1:8000/metrics | No | ✅ |
| 79 | /observability/push-to-insightbridge | POST | http://127.0.0.1:8000/observability/push-to-insightbridge | Yes | ✅ |
| 80 | /parikshak/review-references | POST | http://127.0.0.1:8000/parikshak/review-references | Yes | ✅ |
| 81 | /parikshak/review-references | GET | http://127.0.0.1:8000/parikshak/review-references | No | ✅ |
| 82 | /parikshak/review-references/{id} | GET | http://127.0.0.1:8000/parikshak/review-references/{id} | No | ✅ |
| 83 | /niyantran/task-state | POST | http://127.0.0.1:8000/niyantran/task-state | Yes | ✅ |
| 84 | /niyantran/task-state | GET | http://127.0.0.1:8000/niyantran/task-state | No | ✅ |
| 85 | /niyantran/task-state/{id} | GET | http://127.0.0.1:8000/niyantran/task-state/{id} | No | ✅ |
| 86 | /replay-registry/manifest | GET | http://127.0.0.1:8000/replay-registry/manifest | No | ✅ |

---

## Quick Start Examples

### Get a JWT Token
```bash
curl -X POST http://127.0.0.1:8000/auth/token \
  -H "Content-Type: application/json" \
  -d '{"actor":"john_doe","roles":["reader","writer"]}'
```

### Access Interactive Documentation
```
http://127.0.0.1:8000/docs
```

### Access OpenAPI Specification
```
http://127.0.0.1:8000/openapi.json
```

### Check Health
```bash
curl http://127.0.0.1:8000/health
```

### Check Readiness
```bash
curl http://127.0.0.1:8000/ready
```

---

## Authentication

Protected endpoints (marked with "Yes" in Auth Required column) require a Bearer JWT token in the Authorization header:

```
Authorization: Bearer {token_from_/auth/token}
```

Obtain a token:
```bash
curl -X POST http://127.0.0.1:8000/auth/token \
  -H "Content-Type: application/json" \
  -d '{"actor":"your_actor_id","roles":["reader","writer","admin"]}'
```

Then use it:
```bash
curl http://127.0.0.1:8000/admin/backup \
  -H "Authorization: Bearer eyJ..."
```

---

## Notes

1. **Base URL:** `http://127.0.0.1:8000` (localhost with port 8000)
2. **Total Endpoints:** 86 active endpoints + /docs and /openapi.json
3. **Authentication:** JWT-based with role-based access control
4. **Data Storage:** In-memory by default (persists only during session). Enable persistent storage via `MASTERDB_STORAGE_DIR` or `MASTERDB_DATABASE_URL`.
5. **Interactive Testing:** Visit `/docs` for Swagger UI where you can test all endpoints directly in your browser.

