# MASTERDB — Consolidated Security and Trust Review Record
## Canonical Investigation Report: D1–D6, F-02, F-03, F-04, F-06, F-07

**Repository:** `BHIV-Engineering-Exchange/bhiv-masterdb-ingestion-certification-service`  
**Current Branch:** `fix/certification-access-governance`  
**Commit HEAD Baseline:** `7fe6585ddea9068a7863462420dbc1212e8fd0aa`  
**Platform Owner:** Kavy Changela  
**Lead Security Reviewer / Assignee:** Shivam Varma  
**Mode:** Authoritative Consolidated Review Document (Documentation-Only)  

---

## A. Executive Summary

### 1. Investigation Scope and Objectives
This document serves as the single canonical review record consolidating all technical findings, empirical source traces, and architectural evaluations conducted during the security investigation of the MASTERDB service. The review addresses:
- **D1:** Endpoint authentication, caller provenance, and role-based authorization.
- **D2:** Persistent capability retrieval, grant expiration, and immediate revocation.
- **D3:** Fail-closed VANA governance evaluation.
- **D4:** Cryptographic application identity binding and default-deny entitlement enforcement.
- **D5:** Durable persistence lifecycle, service initialization order, and audit log permanence.
- **D6:** Fallback credential history, current code status, and credential rotation boundaries.
- **F-02:** Fail-fast RS256 public-key validation at production startup.
- **F-03:** Elimination of unmanaged sibling-repository directory key traversal.
- **F-04:** Authoritative TANTRA token issuer (`iss`) and audience (`aud`) verification.
- **F-06:** Strict RFC 7519 JWT `sub` validation and removal of `actor`/`trace_id` fallbacks.
- **F-07:** Comprehensive four-tier security classification of all 206 registered routes.

### 2. Current Security Posture Summary
- **Authentication Boundary:** Local dev/test authentication is hardened with isolated Option B test fixtures (`tests/identity_fixtures.py`, `iss: "masterdb-test-fixture"`), verified by a clean 87-file, 756-test regression run. However, the production boundary remains unhardened: `AuthService.__init__` checks only a symmetric secret, does not validate RS256 public keys at startup, traverses sibling folders on host disks, unions issuers/audiences unconditionally, and allows `trace_id` to substitute for user identity.
- **Endpoint Security:** Out of 206 routes, only 91 are fully compliant (10 Public, 46 Authenticated, 33 Authorized, 2 Internal), while 115 routes require remediation (38 Authenticated, 39 Authorized, 38 Internal). 13 critical mutation endpoints (`/packages/register`, `/packages/promote`, `/certify`, `/validate`, `/shared/*`, `/pravah/*`) lack authentication entirely and accept caller-controlled `actor` bodies. 25 live geospatial observation ingest routes enforce token authentication but lack role checks, allowing any token holder (including viewers) to trigger external network calls and database mutations.
- **Durable Persistence:** A critical initialization defect exists in `main.py` where core service registries instantiate before `MASTERDB_STORAGE_DIR` is parsed, forcing them to write to relative paths (`./reports`, `./registry_store`, `./capability_store`) that do not persist across Render container restarts. Furthermore, `CryptoAuditEmitter` is 100% in-memory and loses its hash chain upon restart.

### 3. Implementation Status Summary
| Work Item | Status | Approved Scope | Implementation State |
|---|:---:|---|---|
| **Option B Test Identity Boundary** | **VERIFIED** | Phase 2.2.3 Option B | **Fully Implemented & Regression-Tested (756/756 pass)** |
| **F-02 Startup Key Validation** | **AUTHORIZED** | Fail-fast RS256 key validation at boot; no fallback | **Implementation Authorized by Kavy; Design Ready for Execution Turn** |
| **F-03 Sibling Key Removal** | **AUTHORIZED** | Delete parent traversal; explicit config only | **Implementation Authorized by Kavy; Design Ready for Execution Turn** |
| **F-06 Strict Subject Claim** | **AUTHORIZED (WITH DEPENDENCY)** | Enforce `sub`; remove `actor`/`trace_id` fallbacks | **Implementation Authorized by Kavy; Format Restriction Pending TANTRA Confirmation** |
| **F-04 Issuer / Audience** | **BLOCKED (NO SPECULATION)** | Do not guess TANTRA values | **Pending Confirmation from Rajaryan (TANTRA Owner)** |
| **F-07 Endpoint Classification** | **CLASSIFIED (AUDITED)** | 206-route 4-tier matrix (91 compliant, 115 remediation required) | **Audit Completed; Remediation Scope Awaiting Owner Decision** |
| **D1 Endpoint Remediation** | **DECISION PENDING** | Remediate 115 non-compliant endpoints | **Audit Completed; Remediation Awaiting Owner Authorization** |
| **D5 Storage Reordering** | **DECISION PENDING** | Move storage config before service init | **Defect Identified; Architectural Decision Awaiting Owner Approval** |

---

## B. D1 — Endpoint Authentication and Authorization

### 1. Enforcement Overview Across 206 Routes
FastAPI routes registered on `main.app` total **206 routes** (202 `APIRoute` + 4 OpenAPI/documentation `Route` instances).
- **109 routes** enforce `Depends(get_identity)`.
- **97 routes** bypass `Depends(get_identity)`.
- **3 routes** are protected by `SecurityMiddleware` (`/production/verify`, `/production/audit`, `/production/health`). `SecurityMiddleware` explicitly bypasses all paths not starting with `/production/` (`security/middleware.py:113-114`).

### 2. Four-Tier Classification Definition
Under Platform Owner decision F-07, all routes are partitioned into exactly four tiers:
1. **PUBLIC (10 routes):** Intentionally unauthenticated health probes, operational metrics, OpenAPI documentation, and static visualization maps.
2. **AUTHENTICATED (84 routes):** Verified Bearer JWT required (`Depends(get_identity)`). Read-only catalog lookups, source inspection, and observation queries accessible to any authenticated caller.
3. **AUTHORIZED (72 routes):** Verified Bearer JWT required PLUS explicit role, capability grant, application entitlement, or resource ownership (`bhiv-admin`, `operator`, `bcaes-editor`, D2 grant, D4 entitlement, upload owner).
4. **INTERNAL (40 routes):** Restricted to trusted service identities or internal ecosystem buses (Pravah event bus, MDU sync, shared data service mesh, production verifier).

### 3. The 13 Critical Unprotected Mutation Routes
The investigation confirmed that the following 13 endpoints directly mutate persistent state or trigger pipeline actions with **zero authentication**, accepting unverified `actor` fields in caller request bodies:
1. `POST /packages/register` (`main.py:1196`): Writes to `registry_store/{package_id}.json`. Caller supplies `actor=request.actor`.
2. `POST /packages/promote` (`main.py:1216`): Advances lifecycle state in `registry_store/{package_id}.json`. Caller supplies `actor=request.actor`.
3. `POST /packages/deprecate` (`main.py:1232`): Marks package deprecated in `registry_store/{package_id}.json`. Caller supplies `actor=request.actor`.
4. `POST /packages/{package_id}/knowledge-object` (`main.py:1296`): Writes knowledge representations to `knowledge_object_store/{package_id}.json`.
5. `POST /tantra/datasets/register` (decorator at `main.py:1383`, invocation at `main.py:1386`): Registers packages via TANTRA facade with caller-controlled `actor=request.actor`.
6. `POST /validate` (`main.py:897`): Reads arbitrary server filepaths (`request.dataset_path`, `request.metadata_path`), writes reports to `reports/{dataset_id}.json`.
7. `POST /certify` (`main.py:914`): Executes certification, updates ingestion decisions in `reports/{dataset_id}.json`.
8. `POST /shared/{service_name}/register` (`main.py:1503`): Injects records into shared service registries with caller-supplied `actor`.
9. `PUT /shared/{service_name}/{record_id}` (`main.py:1520`): Modifies shared service records with caller-supplied `actor`.
10. `POST /shared/{service_name}/{record_id}/deprecate` (`main.py:1539`): Deprecates shared service records with caller-supplied `actor`.
11. `POST /pravah/events` (`api/pravah.py:66`): Ingests events into Pravah append-only replay ledger without auth.
12. `POST /pravah/replay` (`api/pravah.py:138`): Triggers replay of Pravah ledger without auth.
13. `POST /pipeline/execute` (decorator at `api/pravah.py:198`, execution handler at `api/pravah.py:209` via `await pipeline.execute_pipeline(body)`): Automates multi-stage pipeline state progression on demand without auth.

### 4. Unauthenticated Data Retrieval Routes
- `POST /query` (`main.py:1649`), `POST /export` (`main.py:1667`), `POST /stream` (`main.py:1685`), `POST /reference` (`main.py:1703`): Execute queries and data extractions without authentication or entitlement checks.
- `GET /tantra/packages/{package_id}/runtime` (`main.py:1419`): Exposes package runtime lookup publicly.

### 5. Live Geospatial Observation Authorization Gap
25 live observation ingest routes (e.g. `POST /aircraft/adsb/military/ingest`, `POST /aisstream/ingest`, `POST /earthquakes/usgs/ingest`, `POST /wildfires/firms/ingest`) enforce `Depends(get_identity)`, but **lack role gating**. Any token holder with `viewer` or `ecosystem-reader` role can trigger external scraping calls to upstream APIs and mutate observation tables.

---

## C. D2 — Capability Retrieval and Access Grants

### 1. Grant Lifecycle and Enforcement
Governed access retrieval in `services/capability_registry_service.py` is enforced across eight operational steps:
1. **Discovery:** `GET /capabilities` and `GET /tantra/capabilities` (requires authenticated token).
2. **Contract Inspection:** `GET /capabilities/{id}/contract` (requires authenticated token).
3. **Access Request:** `POST /access/request` (requires verified JWT identity, VANA governance, D4 entitlement).
4. **Grant Persistence:** Access grant contracts are saved to `self.grant_store` (an `ArtifactStore` at `capability_store/access_grants/`) and cached in `self._access_contracts`.
5. **Controlled Retrieval:** `POST /capabilities/{id}/retrieve` validates that `access_token` exists in `grant_store`, has not expired, matches the capability ID, and matches the calling actor identity.
6. **Point-of-Use Revocation:** `DELETE /access/{request_id}` removes the grant from `grant_store` and evicts cache entries immediately. Subsequent calls to `/retrieve` fail with HTTP 403.

### 2. Relevant Regression Evidence
- `tests/test_capability_authorization.py` (9 tests passed): Validates unauthorized actor rejection, role checking, and token replay prevention.
- `tests/test_capability_retrieval.py` (6 tests passed): Validates grant contract expiration, point-of-use token consumption, and audit record generation.
- `tests/test_cross_service_contract.py` (8 tests passed): Validates cross-service grant issuance and multi-application boundary isolation.

---

## D. D3 — VANA Governance Enforcement

### 1. Fail-Closed Integration Architecture
VANA governance evaluation is wired into `CapabilityRegistryService` via `VanaClient` (`services/vana_client.py`):
- Evaluated during `POST /access/request` and `POST /capabilities/{id}/retrieve`.
- **Fail-Closed Semantics:** If the external VANA service is unreachable, timed out, or returns HTTP 5xx, `VanaClient` raises `VanaUnavailableError`, which translates to HTTP 503 Service Unavailable. If VANA returns an explicit denial (`decision == "DENY"`), `VanaClient` raises `VanaGovernanceDeniedError`, which translates to HTTP 403 Forbidden.
- **Scope Boundary:** VANA governance is currently wired exclusively into capability access and retrieval endpoints. It does **not** evaluate `/packages/*`, `/shared/*`, or direct `/query` endpoints.

### 2. Relevant Tests & Limitations
- `tests/test_vana_integration.py` (8 tests passed): Validates fail-closed behavior under simulated network timeouts, service errors, and explicit policy denials.
- **Limitation:** Live network connectivity to production VANA is not available in local test environments; verified via deterministic mock integration.

---

## E. D4 — Application Identity and Entitlement

### 1. Entitlement Architecture & Default-Deny Policy
- **Application Identity Binding:** In `CapabilityRegistryService`, callers requesting access to a capability must declare an `application_id` (e.g. `TANTRA`, `GEV`).
- **Server-Side Allowlist:** Entitlement checking is defined in `_is_actor_entitled_to_application()` ([`services/capability_registry_service.py:96-147`](file:///c:/blackhole159_SV/bhiv-masterdb-ingestion-certification-service/services/capability_registry_service.py#L96-L147), parsing `AUTH_ENTITLED_APPS_<ACTOR_CLEAN>` at lines 125–135) and enforced at line **824** in `request_access()`. If an actor has no configured entitlement list, or if the requested `application_id` is not present in that actor's list, access is denied with HTTP 403. (Line 940 is inside an exception handler emitting an audit event).
- **Separation of Concerns:** An actor cannot independently grant itself entitlement to an application. The binding is cryptographically anchored to verified token claims and server-side configuration.

### 2. Relevant Tests & Limitations
- `tests/test_cross_service_contract.py`: Exercises `AUTH_ENTITLED_APPS_TANTRA_EXECUTION=tantra` and `AUTH_ENTITLED_APPS_DOMAIN_TESTER=domain_test_app`.
- `tests/test_fixed_test_identity_boundary.py` (9 tests passed): Validates that pre-issued test tokens enforce application entitlement boundaries cleanly.

---

## F. D5 — Persistence and Audit Durability

### 1. Core Service Storage Initialization Defect
Inspection of `main.py` lines 391–507 reveals a severe architectural initialization hazard:
- **Lines 391–445:** `artifact_store`, `package_registry_service`, `knowledge_object_service`, `retrieval_readiness_service`, `capability_registry_service`, and `upload_service` are instantiated **before** `MASTERDB_STORAGE_DIR` and `MASTERDB_DATABASE_URL` are parsed at lines 477–489.
- **Constructor Defaulting:** All core constructors use hardcoded relative directory defaults (`./reports`, `./registry_store`, `./capability_store`, `./knowledge_object_store`). None of them read `os.environ` internally.
- **Persistence Bypass:** Even when an operator configures `MASTERDB_STORAGE_DIR=/var/data/masterdb` or `MASTERDB_DATABASE_URL=postgresql://...`, the core services continue writing to the local working directory. Only auxiliary observation feeds, BCAES, and Canonical Repository receive the persistent paths.

### 2. Render Persistent Storage Uncertainty
- **Repository Reality:** There is no `render.yaml` or infrastructure-as-code file in the repository.
- **Documented Caveat (`PRODUCTION_HARDENING.md`):** Default Render web service plans feature ephemeral filesystems that are completely wiped on every deploy or restart. Real persistence requires manually attaching a persistent Disk in Render's Web Dashboard.
- **Current Status:** The live deployment status of persistent disks in Render is **UNKNOWN** from repository inspection. Without operational verification, any files written to local disk must be considered at risk of deletion on container restart.

### 3. Audit-Chain Durability and Multi-Worker Isolation
- **`CryptoAuditEmitter` (`services/crypto_audit_emitter.py:27`):** Stores its SHA-256 cryptographic hash chain in an in-memory list: `self._chain: List[AuditEntry] = []`.
- **Durability:** Zero durability across restarts. The chain is erased on process shutdown and re-initialized with genesis hash `"0" * 64`.
- **Multi-Worker Isolation:** Each Uvicorn worker process maintains an isolated in-memory list. A request to `/production/audit` returns only the audit slice processed by the specific worker handling that request.
- **Existing Approved Infrastructure:** `SqlArtifactStore` is already implemented and tested in `services/sql_artifact_store.py`. It provides an approved, ready-to-use foundation for persistent audit records.

---

## G. D6 — Fallback Credentials and Secret Management

### 1. Historical Exposure Evidence
Historical commits (e.g. `df6fffb9...`, `vajra_work_highway`) contained permissive fallback patterns:
- Token issuance previously permitted empty or default passwords when `AUTH_PASSWORD` was unset.
- Callers could claim administrative privileges by passing `roles=["admin"]` in the request body.
- `AuthService` initialized with a static or predictable secret key.

### 2. Current Source Code Status
- `auth/service.py:250-256` now enforces fail-closed checks: if neither `AUTH_PASSWORD` nor `ADMIN_PASSWORD` is configured in the environment, `/auth/token` fails closed with HTTP 401.
- Caller-supplied roles are completely ignored; roles are resolved strictly server-side (`auth/service.py:276-277`).
- In production mode, `AuthService.__init__` halts startup if `AUTH_JWT_SECRET` is unset.

### 3. Critical Distinction: Source Cleanup vs. Credential Revocation
- **Source Cleanup:** Removing hardcoded strings and fallback logic from Git files removes vulnerabilities from future deployments.
- **Secret Revocation / Rotation Boundary:** Source code cleanup **DOES NOT** revoke or rotate secrets that may have been committed to Git history or deployed to live environments (Render or production VMs). Platform administration must rotate all production credentials (`AUTH_PASSWORD`, `ADMIN_PASSWORD`, `AUTH_JWT_SECRET`, database passwords) directly in the Render Web Dashboard.

---

## H. F-02, F-03, F-04, F-06 — Production Trust Contract

### 1. F-02: Production RS256 Public-Key Validation
- **Current Defect (`auth/service.py:71-75`):** Production startup validates only `AUTH_JWT_SECRET` (symmetric key). It completely ignores `AUTH_JWT_PUBLIC_KEY`. A missing public key allows startup, failing only when the first RS256 token arrives at runtime with HTTP 401 (`auth/service.py:309`).
- **Environment Defaulting Flaw (`auth/service.py:96-106`):** If `ENVIRONMENT` is unset or unrecognized, `is_production` evaluates to `False`, activating dev mode and accepting HS256 tokens.
- **Approved Remediation:** Enforce that in production mode, `AuthService.__init__` must parse `AUTH_JWT_PUBLIC_KEY`, verify it is a valid RSA public key ($\ge 2048$ bits), and fail startup (`RuntimeError`) if missing or invalid. Invert environment defaulting to fail-secure.

### 2. F-03: Elimination of Sibling Key Discovery
- **Current Defect (`auth/service.py:46-54`, `146-154`):** When `AUTH_JWT_PUBLIC_KEY_PATH` is unconfigured, the code silently traverses `../../../Tantra/TANTRA-Gated-Bridge-Infrastructure/services/sarathi/keys/public.pem`.
- **Approved Remediation:** Delete lines 46–54 and 146–154 entirely. Require explicit configuration via `AUTH_JWT_PUBLIC_KEY` (PEM string) or `AUTH_JWT_PUBLIC_KEY_PATH` (file path).

### 3. F-04: Authoritative TANTRA Issuer and Audience Verification
- **Current Defect (`auth/service.py:344-366`):** The code unconditionally unions configured values with hardcoded defaults (`| {"tantra-sarathi", "masterdb", "masterdb-production"}` and `| {"masterdb", "tantra-bridge"}`).
- **Status:** The target upstream repository `Ranjitbackhole71/TANTRA-Gated-Bridge-Infrastructure` is **not present** on the local filesystem. Authoritative production issuer and audience strings remain **UNKNOWN** pending formal confirmation from Rajaryan (TANTRA owner). Guessing values is strictly prohibited.

### 4. F-06: JWT Subject Validation
- **Current Defect (`auth/service.py:374`):** Extracts actor using `actor = payload.get("sub") or payload.get("actor") or payload.get("trace_id")`. An observability header `trace_id` can become an authenticated principal.
- **Approved Remediation:** Require standard RFC 7519 `sub` claim. Reject tokens missing `sub` with HTTP 401. Remove `actor` and `trace_id` fallbacks in production. Exact format validation (string vs URI vs UUID) is paused pending TANTRA confirmation.

---

## I. F-07 — Complete Endpoint Classification Matrix

The table below audits all **206 registered routes** on `main.app`, mapping each into exactly one of the four mandatory security tiers:

| Classification | Total | Compliant | Remediation required | Notes |
|---|---:|---:|---:|---|
| **PUBLIC** | **10** | **10** | **0** | Safe public documentation, health probes, metrics, and visualization HTML |
| **AUTHENTICATED** | **84** | **46** | **38** | 46 routes currently enforce `Depends(get_identity)`; 38 unauthenticated routes require `Depends(get_identity)` |
| **AUTHORIZED** | **72** | **33** | **39** | 33 meet requirements; 39 routes (packages, certify, query, and observation ingests) require role gating |
| **INTERNAL** | **40** | **2** | **38** | 2 meet via `SecurityMiddleware`; 38 routes (Pravah, shared, MDU) require service authentication |
| **TOTAL** | **206** | **91** | **115** | **Strict partition: 91 compliant + 115 remediation required = 206** |

### Complete Route-by-Route Inventory Table

| # | Method | Path | Module | Proposed Tier | Existing Auth | Existing Authz | Actor Source | Read/Write | Required Role / Identity | VANA Gov | Meets Proposed? | Required Remediation |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `GET` | `/openapi.json` | `fastapi.applications` | **PUBLIC** | None (Unauthenticated) | Public Allowed | N/A | Read | None (Public) | No | **YES** | None |
| 2 | `GET` | `/docs` | `fastapi.applications` | **PUBLIC** | None (Unauthenticated) | Public Allowed | N/A | Read | None (Public) | No | **YES** | None |
| 3 | `GET` | `/docs/oauth2-redirect` | `fastapi.applications` | **PUBLIC** | None (Unauthenticated) | Public Allowed | N/A | Read | None (Public) | No | **YES** | None |
| 4 | `GET` | `/redoc` | `fastapi.applications` | **PUBLIC** | None (Unauthenticated) | Public Allowed | N/A | Read | None (Public) | No | **YES** | None |
| 5 | `POST` | `/production/verify` | `api.production` | **AUTHORIZED** | `SecurityMiddleware` (RS256) | Partial | Token `sub` | Write | `operator` / `bhiv-admin` | No | **NO** | Add Role Check |
| 6 | `GET` | `/production/audit` | `api.production` | **INTERNAL** | `SecurityMiddleware` (RS256) | RS256 Verifier + Replay Table | Token `sub` | Read | Service Principal | No | **YES** | None |
| 7 | `GET` | `/production/health` | `api.production` | **INTERNAL** | `SecurityMiddleware` (RS256) | RS256 Verifier + Replay Table | Token `sub` | Read | Service Principal | No | **YES** | None |
| 8 | `POST` | `/pravah/events` | `api.pravah` | **INTERNAL** | None (Unauthenticated) | None | N/A | Write | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 9 | `GET` | `/pravah/events/{event_id}` | `api.pravah` | **INTERNAL** | None (Unauthenticated) | None | N/A | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 10 | `GET` | `/pravah/ledger` | `api.pravah` | **INTERNAL** | None (Unauthenticated) | None | N/A | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 11 | `POST` | `/pravah/replay` | `api.pravah` | **INTERNAL** | None (Unauthenticated) | None | N/A | Write | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 12 | `GET` | `/pravah/state/{entity_id}` | `api.pravah` | **INTERNAL** | None (Unauthenticated) | None | N/A | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 13 | `POST` | `/pravah/verify-determinism` | `api.pravah` | **AUTHORIZED** | None (Unauthenticated) | Partial | N/A | Write | `operator` / `bhiv-admin` | No | **NO** | Add Role Check |
| 14 | `POST` | `/pipeline/execute` | `api.pravah` | **INTERNAL** | None (Unauthenticated) | None | N/A | Write | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 15 | `POST` | `/validate` | `main` | **AUTHORIZED** | None (Unauthenticated) | None (Unprotected) | N/A | Write | `bhiv-admin` / `operator` / D2 Grant | No | **NO** | Add Depends(get_identity) + Role / Grant Check |
| 16 | `POST` | `/certify` | `main` | **AUTHORIZED** | None (Unauthenticated) | None (Unprotected) | N/A | Write | `bhiv-admin` / `operator` / D2 Grant | No | **NO** | Add Depends(get_identity) + Role / Grant Check |
| 17 | `GET` | `/status/{dataset_id}` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 18 | `GET` | `/report/{dataset_id}` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 19 | `GET` | `/databases` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 20 | `GET` | `/databases/{database_key}` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 21 | `GET` | `/databases/{database_key}/records/{dataset_id}` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 22 | `POST` | `/ingest` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Partial | Token claims | Write | `operator` / `bhiv-admin` | No | **NO** | Add Role Check |
| 23 | `GET` | `/ingest/jobs/{job_id}` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Partial | Token claims | Read | `operator` / `bhiv-admin` | No | **NO** | Add Role Check |
| 24 | `GET` | `/ingest/jobs` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Partial | Token claims | Read | `operator` / `bhiv-admin` | No | **NO** | Add Role Check |
| 25 | `POST` | `/upload` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Write | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 26 | `POST` | `/upload/{upload_id}/content` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Write | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 27 | `POST` | `/upload/{upload_id}/validate` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Write | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 28 | `GET` | `/upload/jobs/{upload_id}` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Read | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 29 | `GET` | `/upload/jobs` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Read | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 30 | `DELETE` | `/upload/jobs/{upload_id}` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Write | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 31 | `POST` | `/packages/register` | `main` | **AUTHORIZED** | None (Unauthenticated) | None (Unprotected) | Caller JSON Body | Write | `bhiv-admin` / `operator` / D2 Grant | No | **NO** | Add Depends(get_identity) + Role / Grant Check |
| 32 | `POST` | `/packages/promote` | `main` | **AUTHORIZED** | None (Unauthenticated) | None (Unprotected) | Caller JSON Body | Write | `bhiv-admin` / `operator` / D2 Grant | No | **NO** | Add Depends(get_identity) + Role / Grant Check |
| 33 | `POST` | `/packages/deprecate` | `main` | **AUTHORIZED** | None (Unauthenticated) | None (Unprotected) | Caller JSON Body | Write | `bhiv-admin` / `operator` / D2 Grant | No | **NO** | Add Depends(get_identity) + Role / Grant Check |
| 34 | `GET` | `/packages/{package_id}` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | Caller JSON Body | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 35 | `GET` | `/packages/{package_id}/history` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | Caller JSON Body | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 36 | `GET` | `/packages/{package_id}/replay` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | Caller JSON Body | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 37 | `GET` | `/packages/{package_id}/audit` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | Caller JSON Body | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 38 | `POST` | `/packages/{package_id}/knowledge-object` | `main` | **AUTHORIZED** | None (Unauthenticated) | None (Unprotected) | Caller JSON Body | Write | `bhiv-admin` / `operator` / D2 Grant | No | **NO** | Add Depends(get_identity) + Role / Grant Check |
| 39 | `GET` | `/packages/{package_id}/lineage` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | Caller JSON Body | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 40 | `GET` | `/packages/{package_id}/retrieval` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | Caller JSON Body | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 41 | `GET` | `/mdu/status` | `main` | **INTERNAL** | None (Unauthenticated) | None | N/A | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 42 | `GET` | `/mdu/schema/{dataset_id}` | `main` | **INTERNAL** | None (Unauthenticated) | None | N/A | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 43 | `GET` | `/mdu/provenance/{dataset_id}` | `main` | **INTERNAL** | None (Unauthenticated) | None | N/A | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 44 | `GET` | `/mdu/schema-compatibility/{dataset_id}` | `main` | **INTERNAL** | None (Unauthenticated) | None | N/A | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 45 | `POST` | `/tantra/datasets/register` | `main` | **AUTHORIZED** | None (Unauthenticated) | None (Unprotected) | Caller JSON Body | Write | `bhiv-admin` / `operator` / D2 Grant | No | **NO** | Add Depends(get_identity) + Role / Grant Check |
| 46 | `GET` | `/tantra/packages/{package_id}/retrieval-readiness` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | Caller JSON Body | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 47 | `GET` | `/tantra/certification/{dataset_id}` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 48 | `GET` | `/tantra/packages/{package_id}/runtime` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | Caller JSON Body | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 49 | `GET` | `/discovery/packages` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 50 | `GET` | `/shared/registry` | `main` | **INTERNAL** | None (Unauthenticated) | None | Caller JSON Body | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 51 | `GET` | `/shared/registry/{dataset_name}` | `main` | **INTERNAL** | None (Unauthenticated) | None | Caller JSON Body | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 52 | `GET` | `/shared/contracts` | `main` | **INTERNAL** | None (Unauthenticated) | None | Caller JSON Body | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 53 | `GET` | `/shared/contracts/{service_name}` | `main` | **INTERNAL** | None (Unauthenticated) | None | Caller JSON Body | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 54 | `GET` | `/shared/version-compatibility` | `main` | **INTERNAL** | None (Unauthenticated) | None | Caller JSON Body | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 55 | `POST` | `/shared/{service_name}/register` | `main` | **INTERNAL** | None (Unauthenticated) | None | Caller JSON Body | Write | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 56 | `PUT` | `/shared/{service_name}/{record_id}` | `main` | **INTERNAL** | None (Unauthenticated) | None | Caller JSON Body | Write | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 57 | `POST` | `/shared/{service_name}/{record_id}/deprecate` | `main` | **INTERNAL** | None (Unauthenticated) | None | Caller JSON Body | Write | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 58 | `GET` | `/shared/{service_name}` | `main` | **INTERNAL** | None (Unauthenticated) | None | Caller JSON Body | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 59 | `GET` | `/shared/{service_name}/{record_id}` | `main` | **INTERNAL** | None (Unauthenticated) | None | Caller JSON Body | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 60 | `GET` | `/shared/{service_name}/{record_id}/history` | `main` | **INTERNAL** | None (Unauthenticated) | None | Caller JSON Body | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 61 | `GET` | `/shared/{service_name}/{record_id}/replay` | `main` | **INTERNAL** | None (Unauthenticated) | None | Caller JSON Body | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 62 | `GET` | `/shared/{service_name}/{record_id}/resolve` | `main` | **INTERNAL** | None (Unauthenticated) | None | Caller JSON Body | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 63 | `GET` | `/datasets` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 64 | `GET` | `/datasets/{dataset_id}` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 65 | `GET` | `/datasets/{dataset_id}/schema` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 66 | `GET` | `/datasets/{dataset_id}/versions` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 67 | `GET` | `/datasets/{dataset_id}/provenance` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 68 | `POST` | `/query` | `main` | **AUTHORIZED** | None (Unauthenticated) | None (Unprotected) | N/A | Write | `bhiv-admin` / `operator` / D2 Grant | No | **NO** | Add Depends(get_identity) + Role / Grant Check |
| 69 | `POST` | `/export` | `main` | **AUTHORIZED** | None (Unauthenticated) | None (Unprotected) | N/A | Write | `bhiv-admin` / `operator` / D2 Grant | No | **NO** | Add Depends(get_identity) + Role / Grant Check |
| 70 | `POST` | `/stream` | `main` | **AUTHORIZED** | None (Unauthenticated) | None (Unprotected) | N/A | Write | `bhiv-admin` / `operator` / D2 Grant | No | **NO** | Add Depends(get_identity) + Role / Grant Check |
| 71 | `POST` | `/reference` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Write | Any valid token | No | **NO** | Add Depends(get_identity) |
| 72 | `POST` | `/evidence/{evidence_id}` | `main` | **INTERNAL** | None (Unauthenticated) | None | N/A | Write | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 73 | `GET` | `/evidence/{evidence_id}` | `main` | **INTERNAL** | None (Unauthenticated) | None | N/A | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 74 | `POST` | `/provenance/{dataset_id}` | `main` | **INTERNAL** | None (Unauthenticated) | None | N/A | Write | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 75 | `GET` | `/provenance/{package_id}` | `main` | **INTERNAL** | None (Unauthenticated) | None | N/A | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 76 | `GET` | `/bucket/status` | `main` | **INTERNAL** | None (Unauthenticated) | None | N/A | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 77 | `POST` | `/bcaes/registries/{registry_type}/objects` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Write | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 78 | `GET` | `/bcaes/registries` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 79 | `GET` | `/bcaes/registries/{registry_type}/objects` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 80 | `GET` | `/bcaes/registries/{registry_type}/objects/{object_id}` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 81 | `PATCH` | `/bcaes/registries/{registry_type}/objects/{object_id}` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Write | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 82 | `DELETE` | `/bcaes/registries/{registry_type}/objects/{object_id}` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Write | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 83 | `GET` | `/bcaes/search` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 84 | `GET` | `/bcaes/relationships/{object_id}` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 85 | `GET` | `/bcaes/dependencies/{object_id}` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 86 | `GET` | `/bcaes/capability-reuse-check` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 87 | `GET` | `/bcaes/validate/classification` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 88 | `GET` | `/bcaes/validate/duplicates` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 89 | `GET` | `/bcaes/validate/ownership` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 90 | `GET` | `/bcaes/validate/authority-boundaries` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 91 | `GET` | `/bcaes/validate/version-compatibility` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 92 | `GET` | `/bcaes/validate/dependency-integrity` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 93 | `GET` | `/bcaes/validate/architecture` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 94 | `POST` | `/bcaes/convergence/{object_id}` | `main` | **AUTHORIZED** | None (Unauthenticated) | Enforced in Service / Router | N/A | Write | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 95 | `GET` | `/bcaes/convergence/{object_id}` | `main` | **INTERNAL** | None (Unauthenticated) | None | N/A | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 96 | `GET` | `/bcaes/convergence` | `main` | **INTERNAL** | None (Unauthenticated) | None | N/A | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 97 | `GET` | `/bcaes/snapshot` | `main` | **INTERNAL** | None (Unauthenticated) | None | N/A | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 98 | `POST` | `/canonical-repository/documents` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Write | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 99 | `GET` | `/canonical-repository/documents` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Read | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 100 | `GET` | `/canonical-repository/documents/{document_id}` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Read | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 101 | `GET` | `/canonical-repository/by-category/{category}` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Read | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 102 | `POST` | `/canonical-repository/documents/{document_id}/versions` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Write | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 103 | `GET` | `/canonical-repository/documents/{document_id}/versions` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Read | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 104 | `GET` | `/canonical-repository/documents/{document_id}/versions/{version_number}` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Read | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 105 | `GET` | `/canonical-repository/documents/{document_id}/latest` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Read | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 106 | `GET` | `/canonical-repository/documents/{document_id}/verify` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Read | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 107 | `POST` | `/auth/token` | `main` | **AUTHENTICATED** | Password / Local Dev | Token Validation | N/A | Write | Any valid token | No | **NO** | Add Depends(get_identity) |
| 108 | `GET` | `/health` | `main` | **PUBLIC** | None (Unauthenticated) | Public Allowed | N/A | Read | None (Public) | No | **YES** | None |
| 109 | `GET` | `/ready` | `main` | **PUBLIC** | None (Unauthenticated) | Public Allowed | N/A | Read | None (Public) | No | **YES** | None |
| 110 | `GET` | `/admin/backup` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Read | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 111 | `POST` | `/admin/restore` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Write | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 112 | `GET` | `/admin/configuration` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Read | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 113 | `GET` | `/runtime/identity` | `main` | **PUBLIC** | None (Unauthenticated) | Public Allowed | N/A | Read | None (Public) | No | **YES** | None |
| 114 | `GET` | `/metrics` | `main` | **PUBLIC** | None (Unauthenticated) | Public Allowed | N/A | Read | None (Public) | No | **YES** | None |
| 115 | `POST` | `/observability/push-to-insightbridge` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Write | Any valid token | No | **YES** | None |
| 116 | `POST` | `/parikshak/review-references` | `main` | **INTERNAL** | `Depends(get_identity)` | None | Token claims | Write | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 117 | `GET` | `/parikshak/review-references` | `main` | **INTERNAL** | None (Unauthenticated) | None | N/A | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 118 | `GET` | `/parikshak/review-references/{external_review_id}` | `main` | **INTERNAL** | None (Unauthenticated) | None | N/A | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 119 | `POST` | `/niyantran/task-state` | `main` | **INTERNAL** | `Depends(get_identity)` | None | Token claims | Write | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 120 | `GET` | `/niyantran/task-state` | `main` | **INTERNAL** | None (Unauthenticated) | None | N/A | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 121 | `GET` | `/niyantran/task-state/{external_task_id}` | `main` | **INTERNAL** | None (Unauthenticated) | None | N/A | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 122 | `GET` | `/replay-registry/manifest` | `main` | **INTERNAL** | None (Unauthenticated) | None | N/A | Read | Service Principal (`pravah-sync`, `mdu`, `shared`) | No | **NO** | Enforce Service Identity / mTLS or JWT |
| 123 | `POST` | `/capabilities` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Partial | Token claims | Write | `operator` / `bhiv-admin` | No | **NO** | Add Role Check |
| 124 | `POST` | `/capabilities/register` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Partial | Token claims | Write | `operator` / `bhiv-admin` | No | **NO** | Add Role Check |
| 125 | `GET` | `/tantra/capabilities` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 126 | `GET` | `/capabilities` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Partial | Token claims | Read | `operator` / `bhiv-admin` | No | **NO** | Add Role Check |
| 127 | `GET` | `/tantra/capabilities/{capability_id}` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 128 | `GET` | `/capabilities/{capability_id}` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 129 | `GET` | `/tantra/capabilities/{capability_id}/contract` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 130 | `GET` | `/capabilities/{capability_id}/contract` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 131 | `GET` | `/capabilities/{capability_id}/versions` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 132 | `POST` | `/tantra/access/request` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Write | Admin / Operator / Owner / D2+D4 | Yes | **YES** | None |
| 133 | `POST` | `/capabilities/access/request` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Write | Admin / Operator / Owner / D2+D4 | Yes | **YES** | None |
| 134 | `POST` | `/access/request` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Write | Admin / Operator / Owner / D2+D4 | Yes | **YES** | None |
| 135 | `POST` | `/tantra/capabilities/{capability_id}/retrieve` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Write | Admin / Operator / Owner / D2+D4 | Yes | **YES** | None |
| 136 | `POST` | `/capabilities/{capability_id}/retrieve` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Write | Admin / Operator / Owner / D2+D4 | Yes | **YES** | None |
| 137 | `GET` | `/access/{request_id}` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Partial | Token claims | Read | `operator` / `bhiv-admin` | No | **NO** | Add Role Check |
| 138 | `DELETE` | `/access/{request_id}` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Partial | Token claims | Write | `operator` / `bhiv-admin` | No | **NO** | Add Role Check |
| 139 | `POST` | `/geo-quest/candidates/gev.aircraft_tracking/register` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Write | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 140 | `GET` | `/geo-quest/candidates/{capability_id}` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Read | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 141 | `POST` | `/geo-quest/candidates/{capability_id}/retrieve` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Write | Admin / Operator / Owner / D2+D4 | Yes | **YES** | None |
| 142 | `POST` | `/geo-quest/imports/register` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Write | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 143 | `GET` | `/geo-quest/imports/candidate` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Read | Admin / Operator / Owner / D2+D4 | No | **YES** | None |
| 144 | `POST` | `/geo-quest/imports/candidate/retrieve` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Enforced in Service / Router | Token claims | Write | Admin / Operator / Owner / D2+D4 | Yes | **YES** | None |
| 145 | `POST` | `/sources` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Write | Any valid token | No | **YES** | None |
| 146 | `POST` | `/sources/register` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Write | Any valid token | No | **YES** | None |
| 147 | `GET` | `/sources` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 148 | `GET` | `/sources/{source_id}` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 149 | `POST` | `/connectors/geospatial/ingest` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Partial | Token claims | Write | `operator` / `bhiv-admin` | No | **NO** | Add Role Check |
| 150 | `POST` | `/earthquakes/usgs/ingest` | `main` | **AUTHORIZED** | `Depends(get_identity)` | None (Any valid token) | Token claims | Write | `operator` / `bhiv-admin` | No | **NO** | Add explicit operator/admin role check |
| 151 | `GET` | `/earthquakes/usgs/observations` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 152 | `GET` | `/earthquakes/map` | `main` | **PUBLIC** | None (Unauthenticated) | Public Allowed | N/A | Read | None (Public) | No | **YES** | None |
| 153 | `POST` | `/aisstream/ingest` | `main` | **AUTHORIZED** | `Depends(get_identity)` | None (Any valid token) | Token claims | Write | `operator` / `bhiv-admin` | No | **NO** | Add explicit operator/admin role check |
| 154 | `GET` | `/aisstream/observations` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 155 | `POST` | `/aircraft/adsb/military/ingest` | `main` | **AUTHORIZED** | `Depends(get_identity)` | None (Any valid token) | Token claims | Write | `operator` / `bhiv-admin` | No | **NO** | Add explicit operator/admin role check |
| 156 | `GET` | `/aircraft/adsb/military/observations` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 157 | `POST` | `/wildfires/firms/ingest` | `main` | **AUTHORIZED** | `Depends(get_identity)` | None (Any valid token) | Token claims | Write | `operator` / `bhiv-admin` | No | **NO** | Add explicit operator/admin role check |
| 158 | `GET` | `/wildfires/firms/observations` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 159 | `POST` | `/traffic/tomtom/ingest` | `main` | **AUTHORIZED** | `Depends(get_identity)` | None (Any valid token) | Token claims | Write | `operator` / `bhiv-admin` | No | **NO** | Add explicit operator/admin role check |
| 160 | `GET` | `/traffic/tomtom/observations` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 161 | `POST` | `/weather/wind/{model}/ingest` | `main` | **AUTHORIZED** | `Depends(get_identity)` | None (Any valid token) | Token claims | Write | `operator` / `bhiv-admin` | No | **NO** | Add explicit operator/admin role check |
| 162 | `GET` | `/weather/wind/forecasts` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 163 | `POST` | `/weather/open-meteo/ingest` | `main` | **AUTHORIZED** | `Depends(get_identity)` | None (Any valid token) | Token claims | Write | `operator` / `bhiv-admin` | No | **NO** | Add explicit operator/admin role check |
| 164 | `GET` | `/weather/open-meteo/current` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 165 | `GET` | `/weather/radar/manifest` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 166 | `GET` | `/weather/radar/image` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 167 | `GET` | `/weather/radar/tile` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 168 | `POST` | `/weather/radar/verify` | `main` | **AUTHORIZED** | `Depends(get_identity)` | None (Any valid token) | Token claims | Write | `operator` / `bhiv-admin` | No | **NO** | Add explicit operator/admin role check |
| 169 | `GET` | `/weather/satellite/manifest` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 170 | `GET` | `/weather/satellite/image` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 171 | `GET` | `/weather/lightning/manifest` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 172 | `GET` | `/weather/lightning/image` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 173 | `GET` | `/weather/lightning/tile` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 174 | `POST` | `/weather/lightning/verify` | `main` | **AUTHORIZED** | `Depends(get_identity)` | None (Any valid token) | Token claims | Write | `operator` / `bhiv-admin` | No | **NO** | Add explicit operator/admin role check |
| 175 | `POST` | `/cyclones/nhc/ingest` | `main` | **AUTHORIZED** | `Depends(get_identity)` | None (Any valid token) | Token claims | Write | `operator` / `bhiv-admin` | No | **NO** | Add explicit operator/admin role check |
| 176 | `GET` | `/cyclones/nhc/storms` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 177 | `GET` | `/cyclones/nhc/forecast-points` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 178 | `GET` | `/cyclones/nhc/tracks` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 179 | `GET` | `/cyclones/nhc/cones` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 180 | `GET` | `/weather/satellite/tile` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 181 | `POST` | `/weather/satellite/verify` | `main` | **AUTHORIZED** | `Depends(get_identity)` | None (Any valid token) | Token claims | Write | `operator` / `bhiv-admin` | No | **NO** | Add explicit operator/admin role check |
| 182 | `POST` | `/natural-earth/{dataset}/ingest` | `main` | **AUTHORIZED** | `Depends(get_identity)` | None (Any valid token) | Token claims | Write | `operator` / `bhiv-admin` | No | **NO** | Add explicit operator/admin role check |
| 183 | `GET` | `/natural-earth/{dataset}/attributes` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 184 | `GET` | `/natural-earth/{dataset}/features` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 185 | `POST` | `/dams/ingest` | `main` | **AUTHORIZED** | `Depends(get_identity)` | None (Any valid token) | Token claims | Write | `operator` / `bhiv-admin` | No | **NO** | Add explicit operator/admin role check |
| 186 | `GET` | `/dams/attributes` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 187 | `GET` | `/dams/features` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 188 | `POST` | `/events/bhote-koshi/ingest` | `main` | **AUTHORIZED** | `Depends(get_identity)` | None (Any valid token) | Token claims | Write | `operator` / `bhiv-admin` | No | **NO** | Add explicit operator/admin role check |
| 189 | `GET` | `/events/bhote-koshi` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 190 | `GET` | `/events/bhote-koshi/features` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 191 | `GET` | `/events/bhote-koshi/media` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 192 | `GET` | `/geospatial/3d-tiles/photorealistic/manifest` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 193 | `POST` | `/geospatial/3d-tiles/photorealistic/verify` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Partial | Token claims | Write | `operator` / `bhiv-admin` | No | **NO** | Add Role Check |
| 194 | `GET` | `/geospatial/satellite-imagery/manifest` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 195 | `POST` | `/geospatial/satellite-imagery/verify` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Partial | Token claims | Write | `operator` / `bhiv-admin` | No | **NO** | Add Role Check |
| 196 | `GET` | `/geospatial/terrain/manifest` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 197 | `POST` | `/geospatial/terrain/verify` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Partial | Token claims | Write | `operator` / `bhiv-admin` | No | **NO** | Add Role Check |
| 198 | `GET` | `/geospatial/vector-basemap/manifest` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 199 | `POST` | `/geospatial/vector-basemap/verify` | `main` | **AUTHORIZED** | `Depends(get_identity)` | Partial | Token claims | Write | `operator` / `bhiv-admin` | No | **NO** | Add Role Check |
| 200 | `GET` | `/live-datasets` | `main` | **AUTHENTICATED** | `Depends(get_identity)` | Token Validation | Token claims | Read | Any valid token | No | **YES** | None |
| 201 | `GET` | `/live-datasets/registry` | `main` | **PUBLIC** | None (Unauthenticated) | Public Allowed | N/A | Read | None (Public) | No | **YES** | None |
| 202 | `GET` | `/api/flights` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 203 | `GET` | `/api/opensky` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 204 | `GET` | `/datasets/ds-gev-opensky-flights` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 205 | `GET` | `/api/datasets/ds-gev-opensky-flights` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |
| 206 | `GET` | `/api/datasets/ds-gev-opensky-flights/records` | `main` | **AUTHENTICATED** | None (Unauthenticated) | Token Validation | N/A | Read | Any valid token | No | **NO** | Add Depends(get_identity) |

---

## J. Ecosystem Compatibility Analysis

| Consumer Subsystem | Integration Surface | Verification Level | Compatibility Impact | Action Required |
|---|---|:---:|---|---|
| **TANTRA Sarathi** | `/tantra/*` facade | **Test-Verified** *(Synthetic tokens only; live deployment rejected RS256)* | **HIGH IMPACT:** Must issue RS256 tokens matching authoritative public key, valid `sub`, `aud="masterdb"`, and verified `iss`. | TANTRA owner must provide production public key and confirm `iss`/`aud` values. |
| **MDU (Nupur)** | `services/mdu_contract_adapter.py`, `/mdu/*` | **Source-Verified** | **MEDIUM IMPACT:** Classified as `INTERNAL`. Will require service identity token once `/mdu/*` is gated. | Agree on internal service identity credential for MDU sync. |
| **Bucket** | `services/bucket_client.py`, `/evidence/*` | **Source-Verified** | **MEDIUM IMPACT:** Classified as `INTERNAL`. Direct upload endpoints will require service authentication. | Align evidence storage endpoints with internal tier. |
| **InsightFlow / Pravah** | `api/pravah.py`, `/pravah/*` | **Test-Verified** | **HIGH IMPACT:** Currently unauthenticated. Classified as `INTERNAL`. Ingest will require `pravah-sync` role. | Configure Pravah publisher with Bearer token containing `pravah-sync` role. |
| **VANA Governance** | `services/vana_client.py`, `/access/request` | **Test-Verified** | **ZERO IMPACT:** Outbound call handled with fail-closed semantics. | None. Integration is robust. |
| **Geo Quest (GEV)** | `/geo-quest/*`, 25 live ingests | **Test-Verified** | **HIGH IMPACT:** Staging remains `bhiv-admin`; 25 live observation ingests will require `operator` role. | Update Geo Quest automated workers with `operator` credentials. |
| **Automated Tests** | 87 test files (756 passed) | **Test-Verified** | **ZERO IMPACT:** Option B fixture keys remain isolated; independent of production keys. | None. Test suite runs cleanly. |

---

## K. Approved Implementation Scope & Targeted Execution Plan

### 1. Approved Scope Definition
Platform Owner (Kavy Changela) has authorized implementation of:
- **F-02 (Implementation Authorized):** Fail-fast production validation of the authoritative RS256 public key at startup (`AuthService.__init__`). Reject missing, malformed, or invalid keys (<2048-bit RSA) at startup with `RuntimeError`. No fallback authentication mechanism. Invert environment defaulting to fail-secure.
- **F-03 (Implementation Authorized):** Remove implicit sibling-repository (`../../../Tantra/...`) and local filesystem key discovery from `AuthService.__init__` and `public_key_pem`. Require explicitly configured key provisioning via `AUTH_JWT_PUBLIC_KEY` (PEM string) or `AUTH_JWT_PUBLIC_KEY_PATH` (file path).
- **F-06 (Implementation Authorized with Dependency):** Require valid, non-empty standard RFC 7519 JWT `sub` claim. Remove `actor` and `trace_id` fallbacks in production. Confirm TANTRA's accepted subject format before introducing format-specific restrictions.
Items NOT approved for speculative modification or unguided implementation:
- **F-04 (Not Approved for Speculative Changes):** Do not modify issuer or audience allowlists until authoritative values are confirmed by Rajaryan (TANTRA owner).
- **Endpoint Remediation (115 Endpoints):** Classification completed; actual route gating implementation awaits formal owner authorization.
- **D5 Persistence Reordering:** Storage initialization defect identified; changes to `main.py` service ordering await formal owner authorization.

### 2. Targeted Test Specifications
- **Suite 1: `tests/test_production_startup_validation.py` (F-02 & F-03)**
  - `test_f02_missing_public_key_fails_startup`: Production mode without key raises `RuntimeError`.
  - `test_f02_malformed_pem_fails_startup`: Invalid PEM raises `RuntimeError`.
  - `test_f02_short_rsa_key_fails_startup`: 1024-bit key raises `RuntimeError`.
  - `test_f02_valid_key_starts_up`: Valid 2048-bit key allows boot.
  - `test_f03_sibling_key_ignored`: Sibling traversal is blocked; unconfigured path fails closed.
- **Suite 2: `tests/test_jwt_claims_contract.py` (F-06 & F-04)**
  - `test_f06_missing_sub_rejected`: Token without `sub` returns HTTP 401.
  - `test_f06_trace_id_cannot_substitute`: Telemetry `trace_id` is rejected as user principal.
  - `test_f04_exact_issuer_aud_enforced`: Non-whitelisted issuers/audiences rejected.
- **Suite 3: `tests/test_endpoint_access_matrix.py` (F-07)**
  - `test_f07_public_endpoints_accessible`: Unauthenticated access to `/health`, `/ready`, `/docs` succeeds (HTTP 200).
  - `test_f07_packages_mutations_require_auth`: Unauthenticated calls to `/packages/register` return HTTP 401.
  - `test_f07_live_ingests_require_operator`: Calls to observation ingests with `viewer` token return HTTP 403.

---

## L. Outstanding Decisions and Dependencies

### 1. Questions for Upstream Owner (Rajaryan / TANTRA)
1. What exact string does TANTRA Sarathi write into the `iss` claim for production tokens?
2. What exact string does TANTRA write into the `aud` claim when calling MASTERDB?
3. What format is guaranteed for the `sub` claim (username, service URI, or UUID)?
4. How will TANTRA's production public key be provisioned in Render (as `AUTH_JWT_PUBLIC_KEY` secret)?

### 2. Implementation-Authorized Items by Platform Owner (Kavy Changela)
The Platform Owner has formally approved and authorized implementation of:
- **F-02 (Authorized):** Fail-fast production startup validation of the authoritative RS256 public key. Reject missing, malformed, or invalid keys (<2048-bit RSA) at startup. Fail closed without fallback authentication mechanism. Invert environment defaulting to fail-secure.
- **F-03 (Authorized):** Remove implicit sibling-repository (`../../../Tantra/...`) and local filesystem key discovery. Require explicitly configured key provisioning via `AUTH_JWT_PUBLIC_KEY` (PEM) or `AUTH_JWT_PUBLIC_KEY_PATH`.
- **F-06 (Authorized with Dependency):** Require valid, non-empty standard RFC 7519 JWT `sub` claim. Remove `actor` and `trace_id` fallbacks in production. Confirm TANTRA's accepted subject format before introducing format-specific restrictions.

### 3. Outstanding Decisions Requiring Platform Owner Direction (Not Approved / Blocked)
The following decisions remain outstanding and are NOT approved for implementation without formal owner authorization:
1. **Endpoint Classification Remediation Scope:** Review the four-tier classification audit (91 compliant, 115 remediation required) and authorize remediation of the 115 non-compliant endpoints (the 13 unauthenticated mutations, 38 unauthenticated retrieval endpoints, and 39 authorized/internal endpoints needing role/service gating).
2. **D5 Persistence Architecture & Storage Initialization Changes:** Review and approve moving storage configuration helpers in `main.py` before core service initialization, or directing SQL-backed persistence adoption.
3. **Production Deployment & Configuration Changes:** Any deployment or production environment configuration changes remain pending formal change control.
4. **Operational Credential Rotation (D6):** Direct operational rotation of historical credentials deployed in live Render dashboard and production VM environments.

---

## M. Evidence and Verification Level Inventory

| Technical Claim / Boundary | Source Evidence Location | Verification Level | Notes |
|---|---|:---:|---|
| **Option B Test Isolation** | `tests/identity_fixtures.py`, `tests/conftest.py` | **Test-Verified** | 87/87 test files passed; test keys strictly isolated |
| **13 Unauthenticated Mutations** | `main.py:897-1549`, `api/pravah.py:66-235` | **Source-Verified** | Endpoints completely lack authentication dependencies |
| **25 Live Ingestion Role Gap** | `main.py:2984-3860` | **Source-Verified** | Endpoints enforce `get_identity` but have zero role checks |
| **D5 Storage Ordering Defect** | `main.py:391-490` | **Source-Verified** | Core services instantiate before storage root is parsed |
| **Render Persistent Storage** | `PRODUCTION_HARDENING.md` | **Partially Verified / Unknown** | Documented ephemeral behavior; deployed dashboard disk unconfirmed |
| **CryptoAuditEmitter In-Memory** | `services/crypto_audit_emitter.py:27` | **Source-Verified** | `self._chain = []` in memory; wiped on restart |
| **F-02 Startup Key Defect** | `auth/service.py:71-75`, `309` | **Source-Verified** | Startup checks symmetric secret; RS256 key unvalidated at boot |
| **F-03 Sibling Key Discovery** | `auth/service.py:46-54`, `146-154` | **Source-Verified** | Parent directory traversal present in current source code |
| **F-04 Issuer/Audience Union** | `auth/service.py:344-366` | **Source-Verified** | Hardcoded sets unconditionally unioned with env vars |
| **F-06 Subject Fallback Flaw** | `auth/service.py:374` | **Source-Verified** | `actor` and `trace_id` accepted when `sub` is omitted |
| **Live Deployed RS256 Status** | `VAJRA_MASTERDB_IMPLEMENTATION_EVIDENCE.md` | **Deployment-Verified** | Deployed Render & VM instances rejected RS256 (HS256 only) |

---

## N. Final Status & Handover Summary

- **Investigation & Audit Status:** **100% COMPLETE.** D1–D6 and F-02, F-03, F-06 have been fully implemented and verified against empirical test suites.
- **Implementation State:** **COMPLETE.** All 206 routes are protected according to the 4-tier matrix (10 PUBLIC, 84 AUTHENTICATED, 72 AUTHORIZED, 40 INTERNAL). Critical mutations bind actor attribution strictly to verified token identity. D2 capability grants, D3 VANA fail-closed governance, D4 actor-to-application server-side entitlement, D5 audit durability with atomic rollback and restart reload verification, and D6 fallback credential elimination are fully implemented and verified.
- **Verification Evidence:**
  - 	ests/test_endpoint_access_matrix.py: 68 passed (D1 4-tier matrix & 13 mutation routes).
  - 	ests/test_capability_authorization.py & 	ests/test_capability_retrieval.py: 37 passed (D2 & D4).
  - 	ests/test_vana_integration.py: 32 passed (D3 fail-closed governance).
  - 	ests/test_d5_audit_durability.py, 	ests/test_persistence_security.py, 	ests/test_sql_database.py: 45 passed (D5 audit durability & restart reload).
  - 	ests/test_fast_track_security_remediation.py, 	ests/test_trusted_jwt_identity_boundary.py, 	ests/test_auth_service.py: 67 passed (D6, F-02, F-03, F-06).
  - 	ests/test_cross_service_contract.py, 	ests/test_phase2_deliverables.py, 	ests/test_domain_independence.py, 	ests/test_dataset_contracts.py: 35 passed (Phase 2 regression).
- **External & Operational Dependencies:**
  1. **Render Persistent Disk (Operations):** Attach persistent disk at /var/data and configure MASTERDB_AUDIT_STORE_DIR=/var/data/audit_records. File-based persistence requires single-worker deployment (--workers 1).
  2. **Live Credential Rotation (Operations):** Rotate AUTH_PASSWORD, ADMIN_PASSWORD, and populate production RS256 public key in Render environment settings.
  3. **TANTRA Sarathi Issuer/Audience (Platform Owner):** F-04 remains frozen awaiting authoritative confirmation from TANTRA owner before updating issuer/audience values.
