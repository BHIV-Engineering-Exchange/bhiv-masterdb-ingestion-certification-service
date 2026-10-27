# MASTERDB-GEO-QUEST-01 — Evidence & Review Packet
**BHIV-Owned Geospatial Capability Discovery, Validation, Registration & Reuse**

---

## Executive Summary
This Evidence & Review Packet records the technical implementation, read-only inspection, license-safe source selection, and integration of the official **Marine Intelligence** repository (`https://github.com/shravani2207-tech/marine-intelligence-task` @ `03af9e32eeba275592a8e19041d7b51d6139dad7`) and approved **God's Eye View** sources (`https://github.com/bilawalsidhu/gods-eye-view` @ `e7707d9a0f34d9fbffc300023c319f95caa5be30`) into **BHIV MASTERDB** (`masterdb-ingestion-certification-service`).

The technical architecture enforces the canonical principle:
**DISCOVER ONCE $\rightarrow$ VALIDATE ONCE $\rightarrow$ REGISTER ONCE $\rightarrow$ EXPOSE ONCE $\rightarrow$ REUSE ACROSS BHIV**

Separation of logical concepts is strictly maintained:
- **SOURCE**: Where information originates (`SourceRecord` & `SourceRegistryService`)
- **DATASET**: Governed data asset (`KnowledgePackage` & `PackageRegistryService`)
- **CAPABILITY**: What BHIV can do with the data (`Capability` & `CapabilityRegistryService`)

---

## 1. Marine Intelligence Repository Inspection
- **Inspection Status**: **VERIFIED & INTEGRATED**
- **Repository URL**: `https://github.com/shravani2207-tech/marine-intelligence-task`
- **Exact Commit SHA**: `03af9e32eeba275592a8e19041d7b51d6139dad7`
- **Inspected Location**: `scratch/marine-intelligence-task`
- **Purpose**: Maritime Intelligence Unified Data Layer (ports, coastal economic zones, inland waterways, environmental reference data, multimodal logistics parks).
- **Primary Data Sources**: `shipmin.gov.in`, `sagarmala.gov.in`, `mmb.gov.in`, `iwai.nic.in`, `indiawris.gov.in`, `bhuvan.nrsc.gov.in`.

---

## 2. Excluded Commercially Restricted Sources
Per project owner instructions, all commercially restricted or non-commercial research datasets are **EXCLUDED** and blocked at the registry boundary:
- **OpenSky Network** (`src-gev-opensky-adsb`, `cap-gev-flight-tracking`): **EXCLUDED** (Non-commercial research license).
- **TeleGeography Submarine Cable Data**: **EXCLUDED** (Non-commercial CC BY-NC-SA 4.0 license).
- **Enforcement**: Direct code checks in `SourceRegistryService.register_source()` and `CapabilityRegistryService.register_capability()` reject registration of `opensky` or `telegeography` keywords.

---

## 3. Approved & License-Verified Sources & Capabilities
The following license-safe, approved sources and capabilities are registered in MASTERDB:

1. **Marine Intelligence Ports Data Service**
   - **Capability ID**: `cap-marine-intel-ports`
   - **Source ID**: `src-marine-intel-ports`
   - **Dataset ID**: `ds-marine-intel-ports`
   - **License**: `PUBLIC_GOVERNMENT_DATA` (Ministry of Ports, Shipping and Waterways / Sagarmala)
   - **Classification**: **LICENSE VERIFIED**, **TESTED**

2. **CelesTrak Satellite Orbit & Pass Prediction**
   - **Capability ID**: `cap-gev-satellite-pass-prediction`
   - **Source ID**: `src-gev-celestrak`
   - **License**: `US_GOVERNMENT_PUBLIC_DOMAIN`
   - **Classification**: **LICENSE VERIFIED**, **TESTED**

3. **NIFC WFIGS & NASA FIRMS Wildfire Incident Monitoring**
   - **Capability ID**: `cap-gev-wildfire-perimeter-monitoring`
   - **Source ID**: `src-gev-nifc-firms`
   - **License**: `US_GOVERNMENT_PUBLIC_DOMAIN`
   - **Classification**: **LICENSE VERIFIED**, **TESTED**

4. **NOAA GFS & nowCOAST Severe Weather Tracking**
   - **Capability ID**: `cap-gev-weather-forecast-tracking`
   - **Source ID**: `src-gev-noaa-weather`
   - **License**: `US_PUBLIC_DOMAIN`
   - **Classification**: **LICENSE VERIFIED**, **TESTED**

5. **USGS Earthquake Hazard Seismic Detection**
   - **Capability ID**: `cap-gev-earthquake-monitoring`
   - **Source ID**: `src-gev-usgs-seismic`
   - **License**: `US_GOVERNMENT_PUBLIC_DOMAIN`
   - **Classification**: **LICENSE VERIFIED**, **TESTED**

---

## 4. Consumer Integration Status
- **Marine Intelligence Consumer Adapter**: Reuses canonical MASTERDB discovery, contract resolution, access grant, and governed retrieval (`services/masterdb_test_consumer.py`).
- **Simulated Multi-Consumer Test Suite**: Verified for `MARINE_INTEL_APP`, `BHARAT_MALA_APP`, and `VANA_FIN_APP`.
- **Classification**:
  - **TECHNICAL CONSUMER TEST**: **IMPLEMENTED & TESTED**
  - **REAL BHIV PRODUCTION CONSUMER**: **PENDING HUMAN VALIDATION** (Pending production endpoint deployment & credentials).

---

## 5. Requirement Completion Matrix

| Requirement Area | Technical Status | Classification |
| :--- | :--- | :--- |
| **Marine Intelligence Inspection** | Inspected Commit `03af9e32eeba275592a8e19041d7b51d6139dad7` | **VERIFIED** |
| **Restricted Source Exclusion** | OpenSky & TeleGeography blocked at registry boundary | **EXCLUDED** |
| **License-Safe Source Selection** | Registered government/public domain datasets | **LICENSE VERIFIED** |
| **Machine-Readable Contracts** | `GET /capabilities/{id}/contract` | **IMPLEMENTED & TESTED** |
| **Geospatial Connector Adapter** | Extended `GeospatialConnectorAdapter` | **IMPLEMENTED & TESTED** |
| **JWT / RBAC Authorization** | Reused existing MASTERDB Auth | **IMPLEMENTED & TESTED** |
| **Governed Retrieval** | `POST /capabilities/{id}/retrieve` | **IMPLEMENTED & TESTED** |
| **Marine Intelligence Consumer** | Reused MASTERDB 10-step client flow | **IMPLEMENTED & TESTED** |
| **Full Automated Test Suite** | All unit and integration tests passing | **TESTED** |
| **Real Production Deployment** | Pending live endpoints & credentials | **PENDING HUMAN VALIDATION** |

---

# MASTERDB — EVIDENCE REVIEW PACKET (TASK-MASTERDB-PR-001)

**Task ID:** `TASK-MASTERDB-PR-001`  
**Task Title:** MASTERDB Evidence-Driven Production Readiness Closure  
**Engineer:** Pratik Bhuwad  
**Repository:** `bhiv-masterdb-ingestion-certification-service-main`  
**Current Branch:** `fix/masterdb-auth-hardening`  
**Base Commit SHA:** `df6fffb9b5c7413652cd7549a6501805f989ca70` (`df6fffb integrated hari'om`)  
**Target Gatekeeper:** PARIKSHAK / BHEX Engineering Exchange  
**Readiness Status:** **READY FOR SUBMISSION**

---

## 1. Entry Point and System Start Path

- **Application Entry Point:** `main.py:app` (FastAPI ASGI application)
- **Primary Runtime Command (Production):**
  ```powershell
  uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
  ```
- **Local Development / Test Start Path:**
  ```powershell
  .\venv\Scripts\uvicorn main:app --reload --port 8000
  ```
- **Execution Lifecycle & Startup Sequence:**
  1. `services/startup_config.py` runs validation during `main.py` lifespan startup:
     - Detects environment via `ENVIRONMENT` or `APP_ENV`.
     - In `production`: strictly validates that `AUTH_JWT_SECRET` is defined, is not a default/placeholder, and is $\ge 32$ characters.
     - In `production`: strictly validates that persistent storage is configured via `MASTERDB_DATABASE_URL` (non-ephemeral URL) or `MASTERDB_STORAGE_DIR`. Ephemeral targets (`sqlite:///:memory:`, `sqlite://?mode=memory`, empty path) trigger immediate startup failure (`RuntimeError`).
  2. Middleware pipeline registers `RateLimitMiddleware` (with cryptographic JWT signature verification).
  3. Routers initialize: Authentication, Upload, Certification, Governance, Target Ingestion, Runtime Discovery, TANTRA Interface, MDU Adapter, and Health/Readiness Probes.

---

## 2. Top Three Critical Execution Files

Per Section F requirements, the three most critical implementation files are:

| File Path | Role | Key Security / Readiness Mechanism |
| :--- | :--- | :--- |
| **`auth/service.py`** | Authentication & Token Minting | **Fail-Closed Authentication & RBAC Hardening:** Eliminates password bypass when `AUTH_PASSWORD` is unset (`F-AUTH-01`). Prevents caller-supplied actor identity from obtaining administrative privileges without matching `ADMIN_PASSWORD` (`F-AUTH-02`). Enforces $\ge 32$-byte cryptographic secrets in production (`F-AUTH-03`). |
| **`services/startup_config.py`** | Environment & Persistence Guard | **Fail-Closed Production Safety Gates:** Enforces non-ephemeral database configuration in production mode. Distinguishes durable file SQLite (`sqlite:///path/to/db.sqlite`) from ephemeral SQLite (`:memory:`) via `is_sqlite_url_ephemeral()` (`F-PERSIST-01..03`). Sanitizes connection URIs in logs to prevent credential leakage. |
| **`middleware/rate_limit_middleware.py`** | Request Rate Limiting | **Cryptographic Token Verification:** Replaces untrusted decoding of JWT headers/payloads with full cryptographic signature verification (`jwt.decode`) against the server signing key before extracting rate-limit subject keys, preventing unauthenticated quota exhaustion attacks (`F-AUTH-04`). |

---

## 3. Before-and-After Behavior Matrix

| Finding / Gap | Vulnerable "Before" Behavior | Hardened "After" Behavior |
| :--- | :--- | :--- |
| **F-AUTH-01: Password Bypass** | If `AUTH_PASSWORD` was unset in environment, `/auth/token` issued tokens to unauthenticated callers. | When `AUTH_PASSWORD` is unset or password check fails, request immediately fails closed with HTTP 401 (`Invalid credentials` / `Authentication is not configured`). |
| **F-AUTH-02: Actor Privilege Escalation** | Callers could supply `actor="admin"` or `actor="bhiv-admin"` to obtain administrator roles without providing an admin password. | Actor string has zero role influence. Callers only receive `admin` or `bhiv-admin` roles if they supply a valid `ADMIN_PASSWORD`. Standard users receive standard roles only and get HTTP 403 on protected routes. |
| **F-AUTH-03: Production Secret Enforcement** | Short, default, or missing JWT secrets were silently accepted in production mode. | Startup strictly enforces that production JWT signing keys are $\ge 32$ characters and non-default; fails startup with `RuntimeError` otherwise. |
| **F-AUTH-04: Rate-Limit Identity Spoofing** | Rate limiter extracted `sub` claim from unverified JWT payloads, enabling denial-of-service against arbitrary actors. | Rate limiter cryptographically verifies token signature before using subject; forged or unverified tokens fall back to client IP address. |
| **F-PERSIST-01 / 02: Ephemeral Persistence in Prod** | Production environments could silently initialize in-memory SQLite (`:memory:`), causing permanent data loss on container restart. | Production startup rejects in-memory SQLite and missing persistence with `RuntimeError`, forcing operators to configure durable storage. |
| **F-PERSIST-03: SQLite URI Parsing** | Valid persistent SQLite file paths (`sqlite:///data.db`) were mistakenly treated as ephemeral due to naïve prefix checks. | Added robust regex-based URI parser (`is_sqlite_url_ephemeral`) that correctly recognizes disk-backed SQLite as persistent while rejecting `:memory:`. |
| **F-PERSIST-04: Passive Health Check** | `/ready` probe returned `200 OK` by merely checking configuration variable presence without testing storage connectivity. | `/ready` probe actively executes `ping()` (`SELECT 1` on SQL, write-probe on filesystem), returning HTTP 503 (`status: degraded`) on failure. |

---

## 4. Real Request and Response Examples (Sanitized)

### 4.1 Missing Credentials / Unauthenticated Attempt (F-AUTH-01)
- **Request:**
  ```http
  POST /auth/token HTTP/1.1
  Host: localhost:8000
  Content-Type: application/json

  {
    "actor": "any_caller",
    "password": ""
  }
  ```
- **Response:**
  ```http
  HTTP/1.1 401 Unauthorized
  Content-Type: application/json

  {
    "detail": "Invalid credentials."
  }
  ```

### 4.2 Standard User Requesting Administrator Privileges (F-AUTH-02)
- **Request:**
  ```http
  POST /auth/token HTTP/1.1
  Host: localhost:8000
  Content-Type: application/json

  {
    "actor": "admin",
    "password": "[REDACTED_STANDARD_PASSWORD]"
  }
  ```
- **Response (Issued with standard role only):**
  ```http
  HTTP/1.1 200 OK
  Content-Type: application/json

  {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.sanitized.token",
    "token_type": "bearer",
    "roles": ["ingest", "certify", "query"]
  }
  ```
- **Follow-up Access to Admin Endpoint:**
  ```http
  GET /admin/system-status HTTP/1.1
  Host: localhost:8000
  Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.sanitized.token
  ```
  ```http
  HTTP/1.1 403 Forbidden
  Content-Type: application/json

  {
    "detail": "Admin privileges required."
  }
  ```

### 4.3 Persistence Readiness Probe Active Verification (F-PERSIST-04)
- **Healthy Storage Response:**
  ```http
  GET /ready HTTP/1.1
  Host: localhost:8000
  ```
  ```http
  HTTP/1.1 200 OK
  Content-Type: application/json

  {
    "status": "ok",
    "persistence": "ready",
    "backend": "sql"
  }
  ```

- **Degraded Storage Response (Injected Disconnect):**
  ```http
  HTTP/1.1 503 Service Unavailable
  Content-Type: application/json

  {
    "status": "degraded",
    "persistence": "unavailable",
    "error": "Storage backend ping failed"
  }
  ```

---

## 5. File Inventory: Added, Modified, and Untouched

### 5.1 Modified Tracked Files (17 Files)
1. `.env.example`: Documented authentication passwords, persistence variables, and runtime modes.
2. `README.md`: Operational configuration guide, fail-closed security documentation, test commands.
3. `auth/service.py`: Fail-closed token issuance, separate admin credentials, JWT secret validation.
4. `main.py`: Active storage ping in `/ready` probe; returns 503 on persistence failure.
5. `middleware/rate_limit_middleware.py`: Cryptographic JWT signature verification before rate limit keying.
6. `services/artifact_store.py`: Added active filesystem `ping()` method.
7. `services/sql_artifact_store.py`: Added active database `ping()` method executing `SELECT 1`.
8. `services/startup_config.py`: Fail-closed production guards, `is_sqlite_url_ephemeral()`, credential sanitization.
9. `services/masterdb_test_consumer.py`: Updated test helper authentication headers.
10. `tests/conftest.py`: Added baseline test credentials for seamless regression execution.
11. `tests/test_authentication_security.py`: Added 20 security regression tests for F-AUTH-01 through 04.
12. `tests/test_capability_authorization.py`: Adjusted test token fixtures.
13. `tests/test_capability_contract.py`: Adjusted test token fixtures.
14. `tests/test_capability_discovery.py`: Adjusted test token fixtures.
15. `tests/test_capability_retrieval.py`: Adjusted test token fixtures.
16. `tests/test_domain_independence.py`: Adjusted test token fixtures.
17. `tests/test_real_e2e_flow.py`: Aligned E2E client test credentials.

### 5.2 Added Test Files (1 File)
- `tests/test_persistence_security.py`: 21 automated regression tests verifying production persistence guards.

### 5.3 Core Architecture Files (Untouched)
- `bcaes_registry/*`, `canonical_repository/*`, `evaluation_engine/*`: Untouched.
- `database_targets/*`: Preserved existing routing logic and storage adapters.
- `services/certification_service.py`, `services/validation_service.py`: Business logic preserved.

---

## 6. Invalid Input, Missing Config & Failure Handling

| Scenario | System Behavior | HTTP Status / Exit Code |
| :--- | :--- | :---: |
| Missing password during login | Request rejected, no token issued | `401 Unauthorized` |
| Invalid password | Request rejected | `401 Unauthorized` |
| Caller requests admin role with standard password | Standard token minted; `admin` / `bhiv-admin` roles stripped | `200 OK` (unprivileged) |
| Standard token calls admin route | Access denied | `403 Forbidden` |
| Production mode without `AUTH_JWT_SECRET` | Startup aborts with `RuntimeError` | Exit Code `1` |
| Production mode with short JWT secret (< 32 chars) | Startup aborts with `RuntimeError` | Exit Code `1` |
| Production mode with `sqlite:///:memory:` | Startup aborts with `RuntimeError` | Exit Code `1` |
| Storage backend unreachable during health probe | Probe fails closed, credentials redacted | `503 Service Unavailable` |
| Uncertified dataset ingestion submission | Rejected at certification validation gate | `422 Unprocessable Entity` |

---

## 7. Test Results & Verification Record

- **Test Framework:** `pytest` (Python 3.12.7, Windows AMD64)
- **Command:** `.\venv\Scripts\pytest -q`
- **Total Test Cases:** **445**
- **Passed:** **445 (100%)**
- **Failed:** **0**
- **Skipped:** **0**
- **Warnings:** 16 (Starlette TestClient deprecation warning; RFC 7518 key-length warnings on synthetic short test keys).
- **Execution Duration:** 179.87s

---

## 8. External Integrations & Boundary Status

Per strict evidence rules, external systems are documented transparently:

1. **MDU (`MDU_BASE_URL`):** `BLOCKED / PLACEHOLDER` — Unconfigured in local environment; falls back gracefully to local placeholder contract (`/mdu/status` reports `live: false`).
2. **Pravah Bucket (`PRAVAH_BHIV_BUCKET`):** `BLOCKED / NOT CONFIGURED` — Unset in local environment; calls raise `BucketUnavailableError` (HTTP 503) rather than silently mocking success.
3. **InsightFlow Observability Bridge:** `BLOCKED / NOT CONFIGURED` — Gracefully reports `{"pushed": false, "reason": "PRAVAH_BHIV_INSIGHT_FLOW_BRIDGE is not set in this environment."}`.

---

## 9. Conclusion
`TASK-MASTERDB-PR-001` has satisfied all technical, security, persistence, and verification criteria with zero regressions across the 445-test suite.
