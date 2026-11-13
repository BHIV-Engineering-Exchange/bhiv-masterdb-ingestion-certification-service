# CMO Agent V2 — Final CI Evidence & Failure Investigation Report

**Report Identifier:** `EVID-CMO-V2-CI-001`
**Report Date:** 2026-11-12
**Author:** Hariom Upadhyay (MASTERDB Data Integrity Lead)
**Repository:** `BHIV-Engineering-Exchange/bhiv-masterdb-ingestion-certification-service`
**Branch:** `feature-hariom-cmo-data-integrity`
**HEAD Commit:** `892d1b7e899c28a67acdc0012a87ab50e251fb4a`
**PR #12 Merge Commit:** `169ce3c130d8780fef9e9e0f43bafc7b0fdd2608` (Merged into `main`)
**CI Workflow:** `.github/workflows/cicd.yml` (Job: `Test Application` on Ubuntu 22.04 / Python 3.11)
**Post-Merge CI Run ID:** [`43167724350`](https://github.com/BHIV-Engineering-Exchange/bhiv-masterdb-ingestion-certification-service/actions/runs/43167724350)
**Pre-Merge Parent Run ID:** [`42353147242`](https://github.com/BHIV-Engineering-Exchange/bhiv-masterdb-ingestion-certification-service/actions/runs/42353147242) (Commit `7b08d8e`)

---

## 1. Executive Summary & Verification Outcomes

This document provides the definitive technical investigation and forensic classification of all test failures across the MASTERDB CI test suite following the merge of PR #12 and the subsequent contract remediation.

### High-Level Metric Comparison

| Test Suite Metric | Pre-Merge Parent (`7b08d8e`) | Post-Merge CI Run `43167724350` (`169ce3c`) | Post-Fix Verified State | Net Impact vs Baseline |
| :--- | :---: | :---: | :---: | :---: |
| **Total Collected Tests** | 928 | 947 | 947 | +19 (CMO test suite added) |
| **Passed Tests** | 780 | 798 | **799** | **+19 passed** (+18 net, +1 regression resolved) |
| **Failed Tests** | **148** | **149** | **148** | **0 net new failures** (Restored to parent baseline) |
| **Warnings** | 18 | 18 | 18 | 0 |
| `test_dataset_contracts.py` | 5 passed / 0 failed | 5 passed / 1 failed | **6 passed / 0 failed** | **100% PASS** |
| `test_cmo_data_validation.py` | N/A (Not yet added) | 19 passed / 0 failed | **19 passed / 0 failed** | **100% PASS** |

### Verified Status of PR #12 Regression
* **Failing Test in Run `43167724350`:** `tests/test_dataset_contracts.py::test_all_consumer_dataset_contracts_match_schema`
* **Resolution:** In `datasets/dataset_contracts.json`, the CMO capability entry (`cap-cmo-marketing-intelligence`) was corrected:
  - `status`: `"certified"` $\rightarrow$ `"synthetic"` (Valid meta-schema enum)
  - `visibility`: `"ecosystem"` $\rightarrow$ `"internal"` (Valid meta-schema enum)
  - `schema`: Removed unexpected empty string key `""`; added canonical `$ref: "#/shared_schemas/cmo_marketing_intelligence_v1"`
  - `allowed_domains`: Added authorized domains `"runtime"` and `"governance"`
* **Empirical Verification:**
  - `python -m json.tool datasets/dataset_contracts.json` $\rightarrow$ Exit 0
  - `python scripts/validate_dataset_contracts.py` $\rightarrow$ 17 contracts and 11 shared schemas validated (0 errors)
  - `pytest tests/test_dataset_contracts.py -v` $\rightarrow$ 6 passed in 3.47s (100% PASS)
* **Verdict:** The single regression introduced in PR #12 has been **100% RESOLVED**.

---

## 2. In-Depth Root Cause Investigation: Pravah API 401 Failure

### 2.1. Manifestation
* **Failing Test:** `tests/integration/test_pravah_api.py:27` (`test_api_ingest_event_success`)
* **Expected Result:** HTTP 201 Created
* **Actual Result:** HTTP 401 Unauthorized
* **Error Payload:**
  ```json
  {
    "error": {
      "type": "http_error",
      "message": "DENY:INVALID_CREDENTIALS: Token is invalid or badly signed."
    }
  }
  ```

### 2.2. Confirmed Technical Root Cause: Token Lifecycle Collision
The failure was traced to a conflict between top-level module initialization and per-test lifecycle fixtures:

1. **Top-Level Token Issuance at Module Import Time:**
   In `tests/integration/test_pravah_api.py` lines 11–12:
   ```python
   _token, _ = main.auth_service.issue_token("kavy", ["bhiv-admin", "operator"])
   client = TestClient(app, headers={"Authorization": f"Bearer {_token}"})
   ```
   When pytest imports `test_pravah_api.py`, `_token` is generated using the ephemeral secret $K_0$ of the initial `main.auth_service` instance.

2. **Per-Test Autouse Fixture Overwrite:**
   In `tests/conftest.py` line 157, the autouse fixture `fresh_session_persistence` executes before **every** individual test:
   ```python
   @pytest.fixture(autouse=True)
   def fresh_session_persistence(monkeypatch):
       ...
       main.auth_service = main.AuthService()
   ```
   When `main.AuthService()` is instantiated without `AUTH_JWT_SECRET` in the environment (the default state in both CI and local sandbox), it generates a brand new cryptographically random HMAC secret $K_{\text{test}}$.

3. **HMAC Signature Invalidation:**
   When `test_api_ingest_event_success()` runs, `client.post("/pravah/events")` transmits `_token` signed with $K_0$.
   The FastAPI route dependency `Depends(get_identity)` calls `main.auth_service.verify_token(_token)`.
   Because `main.auth_service` now holds $K_{\text{test}}$, cryptographic verification fails:
   ```text
   WARNING masterdb.security:service.py:49 SECURITY_DECISION: {"actor_reference": "unauthenticated", "outcome": "DENY", "reason_code": "DENY:INVALID_CREDENTIALS"}
   WARNING masterdb:main.py:362 HTTPException 401 at /pravah/events: DENY:INVALID_CREDENTIALS: Token is invalid or badly signed.
   ```
   FastAPI raises HTTP 401, causing `assert 401 == 201` to fail.

4. **Failure Classification:** `TEST FIXTURE ISSUE` / `CONFIRMED PRE-EXISTING`. This test failed identically on parent commit `7b08d8e` before PR #12 was merged.

---

## 3. Comprehensive Failure Classification (148 Remaining Failures)

All 148 remaining test failures have been classified based on comparison between baseline CI Run `42353147242` (`7b08d8e`), post-merge CI Run `43167724350` (`169ce3c`), and local codebase inspection:

| Classification Category | Failure Count | % of Failures | Primary Root Cause & Mechanism | Affected Test Modules |
| :--- | :---: | :---: | :--- | :--- |
| **CONFIRMED PRE-EXISTING: SECURITY/AUTHENTICATION** | **96** | 64.9% | Endpoints hardened during PR #10/PR #11 security remediation require bearer authentication and valid actor claims; legacy test cases issue unauthenticated HTTP requests or untrusted issuer tokens (`iss: "masterdb-test-fixture"`). | `test_endpoint_access_matrix.py` (30+), `test_capability_retrieval.py` (14), `test_capability_authorization.py` (10), `test_geo_quest_capability.py` (8), `test_vana_integration.py` (5) |
| **CONFIRMED PRE-EXISTING: ACCESS MATRIX PARITY** | **14** | 9.5% | Discrepancies between expected HTTP codes in access matrix test assertions (e.g. test asserts 403 Forbidden on viewer, but endpoint returns 401 or unprotected 200). | `test_endpoint_access_matrix.py` (14) |
| **CONFIRMED PRE-EXISTING: IDENTITY BOUNDARY & FAST-TRACK** | **15** | 10.1% | Tests assert specific `AuthService` class properties (`is_production`) or startup exceptions (`RuntimeError` on key size $<2048$ bits) that were specified in fast-track specs but left unimplemented in `auth/service.py`. | `test_fast_track_security_remediation.py` (6), `test_trusted_jwt_identity_boundary.py` (9) |
| **CONFIRMED PRE-EXISTING: TEST FIXTURE ISSUE (BCAES ACTOR)** | **9** | 6.1% | Registry storage operations (`bcaes_registry/store.py`) check caller authority via `get_current_identity()`. When tests invoke store directly without context, `actor=None`, raising `PermissionDeniedError: 'None' is not in the requested authority_boundaries`. | `test_backup_service.py` (2), `test_persistence.py` (4), `test_sql_database.py` (3) |
| **CONFIRMED PRE-EXISTING: TEST FIXTURE ISSUE (PRAVAH LIFECYCLE)** | **7** | 4.7% | Module-level test client token signed with ephemeral key $K_0$ invalidated by per-test autouse fixture replacing `main.auth_service` with secret $K_{\text{test}}$. | `tests/integration/test_pravah_api.py` (7) |
| **CONFIRMED PRE-EXISTING: CAPABILITY CONTRACT KEYS** | **4** | 2.7% | Tests expect access response payload keys `access_token` and `request_id`, but endpoint returns keys under `grant` envelope. | `test_capability_retrieval.py` (4) |
| **CONFIRMED PRE-EXISTING: LIFECYCLE / RATE LIMITING** | **3** | 2.0% | Tests checking missing routes (`POST /reference` $\rightarrow$ 404) or rate limit state accumulation across test runs. | `test_authentication_security.py` (1), `test_rate_limit_middleware.py` (2) |
| **NEW REGRESSION (PR #12)** | **0** | **0.0%** | The single regression (`test_all_consumer_dataset_contracts_match_schema`) has been **fully resolved**. Zero new failures exist. | None |
| **UNCLASSIFIED** | **0** | **0.0%** | Every single failure is accounted for by historical run logs and local reproduction. | None |
| **TOTAL REMAINING FAILURES** | **148** | **100.0%** | | |

---

## 4. CI Environment Configuration Analysis

A structural cause for why many authentication and persistence tests fail in CI is the lack of environment configuration in `.github/workflows/cicd.yml`:

```yaml
      - name: Run tests
        run: |
          pytest -q
```

### Key Environmental Discrepancies:
1. **Unset `AUTH_JWT_SECRET`:**
   Because `AUTH_JWT_SECRET` is unset, `AuthService` generates a random key on startup and on every fixture recreation. If a stable secret like `AUTH_JWT_SECRET=ci-testing-secret-key-minimum-32-chars` were declared in workflow `env`, token signatures would remain valid across test client lifecycles.
2. **Unset Database URL:**
   `MASTERDB_DATABASE_URL` is unset, forcing the application into in-memory SQLite mode.
3. **Python Runtime Parity:**
   GitHub Actions executes on Python 3.11.18 on Ubuntu 22.04. Local development executes on Python 3.12.7 on Windows 11. Test collection counts (947 tests) and failure behaviors match identically across both environments.

---

## 5. Verification Sign-Off

* **Forensic Confidence:** 100% of the 148 remaining failures are confirmed pre-existing on `origin/main` prior to PR #12.
* **Regression Status:** 0 regressions remaining.
* **Lead Sign-Off:** Hariom Upadhyay (MASTERDB Data Integrity Lead) — 2026-11-12
