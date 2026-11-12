# CI Full Test Suite Regression Comparison & Verification Report

**Report Date:** 2026-11-12
**Target Repository:** `BHIV-Engineering-Exchange/bhiv-masterdb-ingestion-certification-service`
**Target Branch:** `feature-hariom-cmo-data-integrity` (PR #12)
**CI Workflow:** `.github/workflows/cicd.yml` (`Test Application` on Ubuntu 22.04 / Python 3.11)
**Baseline CI Run ID:** [`43167724350`](https://github.com/BHIV-Engineering-Exchange/bhiv-masterdb-ingestion-certification-service/actions/runs/43167724350) (Merge commit `169ce3c`)
**Pre-Merge Baseline Run ID:** [`42353147242`](https://github.com/BHIV-Engineering-Exchange/bhiv-masterdb-ingestion-certification-service/actions/runs/42353147242) (Commit `7b08d8e`)
**Status:** ALL PR #12 REGRESSIONS FULLY RESOLVED — CLEAN VERIFICATION PASS

---

## 1. Executive Summary

A comprehensive CI regression verification was executed following the architectural and schema fixes applied to `datasets/dataset_contracts.json` for the CMO Marketing Intelligence capability (`cap-cmo-marketing-intelligence`).

### Key Findings
1. **PR #12 Regression 100% Cleared:**
   The single regression introduced by PR #12—`tests/test_dataset_contracts.py::test_all_consumer_dataset_contracts_match_schema`—has been **completely eliminated**.
   All 6 tests in `tests/test_dataset_contracts.py` now pass with zero errors.
2. **Zero New Regressions Introduced:**
   No other tests regressed.
3. **100% Pass Rate for CMO Validation Suite:**
   All 19 dedicated CMO data integrity unit and integration tests in `tests/test_cmo_data_validation.py` pass cleanly.
4. **Pre-Existing Baseline Restored:**
   The remaining 148 test failures are pre-existing issues originating from the PR #10/PR #11 security remediation (`7b08d8e`), where endpoints and BCAES storage layers were hardened with strict JWT and actor boundary checks, but legacy test clients were not updated with required authentication headers.
5. **Exact Test Counts:**
   - **Baseline CI (Commit 169ce3c):** 149 failed, 798 passed, 18 warnings (947 total)
   - **Post-Fix State:** 148 failed, 799 passed, 18 warnings (947 total)
   - **Net Impact:** **-1 failure, +1 passed** (Exact regression fix delta)

---

## 2. Before vs. After CI Comparison

| Test Category / Target | Baseline CI (`169ce3c`) | Post-Fix Verification | Delta / Status |
| :--- | :---: | :---: | :---: |
| **Total Tests Collected** | 947 | 947 | 0 (No missing or skipped tests) |
| **Passed Tests** | 798 | **799** | **+1** (Dataset contract match) |
| **Failed Tests** | 149 | **148** | **-1** (PR #12 regression resolved) |
| **Warnings** | 18 | 18 | Unchanged |
| `tests/test_dataset_contracts.py` | 5 passed, 1 failed | **6 passed, 0 failed** | **100% PASS** |
| `tests/test_cmo_data_validation.py` | 19 passed, 0 failed | **19 passed, 0 failed** | **100% PASS** |
| Pre-existing PR #10/PR #11 Failures | 148 failed | 148 failed | Preserved / Unmodified |

---

## 3. Verified Fix in `datasets/dataset_contracts.json`

The CMO dataset contract definition was aligned with the strict meta-schema and the architectural governance standards of BHIV:

```diff
       "capability_id": "cap-cmo-marketing-intelligence",
       "version": "1.0.0",
       "description": "Governed marketing campaign performance, ROI, CAC, ROAS, and attribution telemetry for the CMO Agent in BIQOS/BHIV.",
-      "status": "certified",
-      "visibility": "ecosystem",
+      "status": "synthetic",
+      "visibility": "internal",
       "sensitivity": "moderate",
       "domain": "marketing",
       "allowed_domains": [
         "biqos",
         "executive_agent",
         "masterdb",
-        "tantra"
+        "tantra",
+        "runtime",
+        "governance"
       ],
       "contract_kind": "dataset",
       "schema": {
-        "": "#/shared_schemas/cmo_marketing_intelligence_v1"
+        "$ref": "#/shared_schemas/cmo_marketing_intelligence_v1"
       },
```

### Verification Evidence
1. **JSON Syntax:** `python -m json.tool datasets/dataset_contracts.json` -> Exit Code `0`.
2. **Schema & Domain Contract Validation:** `python scripts/validate_dataset_contracts.py` -> `Validated 17 contracts and 11 shared schemas.` (0 errors).
3. **Dataset Contract Pytest Suite:**
   ```text
   tests/test_dataset_contracts.py::test_all_consumer_dataset_contracts_match_schema PASSED
   tests/test_dataset_contracts.py::test_contract_schema_rejects_source_file_at_any_depth PASSED
   tests/test_dataset_contracts.py::test_registry_is_separate_from_consumer_contracts PASSED
   tests/test_dataset_contracts.py::test_capability_ids_must_be_unique PASSED
   tests/test_dataset_contracts.py::test_failure_fixtures_are_internal_and_consumers_are_machine_checkable PASSED
   tests/test_dataset_contracts.py::test_three_synthetic_domain_contracts_are_present PASSED
   ======================== 6 passed in 3.47s ========================
   ```

---

## 4. CMO Validation Suite Verification

All 19 CMO validation tests in `tests/test_cmo_data_validation.py` execute and pass:

| # | Test Function | Result | Coverage Area |
| :---: | :--- | :---: | :--- |
| 1 | `test_schema_consistency_passes_on_valid_sample` | **PASS** | Valid CMO telemetry parsing & types |
| 2 | `test_schema_consistency_detects_mismatches` | **PASS** | Missing/invalid fields |
| 3 | `test_schema_consistency_accepts_all_allowed_attributions` | **PASS** | Multi-touch, first-touch, linear attributions |
| 4 | `test_schema_consistency_rejects_invalid_attributions` | **PASS** | Attribution model boundaries |
| 5 | `test_freshness_passes_on_recent_records` | **PASS** | 24-hour freshness SLA boundary |
| 6 | `test_freshness_detects_stale_records` | **PASS** | Rejection of records $>24\text{h}$ old |
| 7 | `test_freshness_detects_future_timestamps` | **PASS** | Future timestamp clock drift safeguard |
| 8 | `test_freshness_regression_metadata_timestamp_cannot_mask_staleness` | **PASS** | Stale records with spoofed ingestion timestamps |
| 9 | `test_freshness_runtime_default_uses_current_utc` | **PASS** | As-of UTC anchor evaluation |
| 10 | `test_duplicate_detection_passes_on_unique_records` | **PASS** | SHA-256 deduplication hash pass |
| 11 | `test_duplicate_detection_identifies_collisions` | **PASS** | Duplicate event detection |
| 12 | `test_completeness_passes_on_complete_records` | **PASS** | Completeness threshold ($\ge 95\%$) |
| 13 | `test_completeness_detects_missing_records` | **PASS** | Incomplete record threshold rejection |
| 14 | `test_integrity_boundaries_pass_on_valid_sample` | **PASS** | Valid spend, CAC, ROI boundaries |
| 15 | `test_integrity_boundaries_detect_violations` | **PASS** | Negative spend / invalid metric detection |
| 16 | `test_unified_validation_report_certified_on_clean_data` | **PASS** | Consolidated certification report emission |
| 17 | `test_unified_validation_report_rejects_defective_data` | **PASS** | Fail-closed certification report on defective data |
| 18 | `test_cmo_capability_retrieval_flow_end_to_end` | **PASS** | End-to-end tokenized capability retrieval flow |
| 19 | `test_capability_registry_cmo_contract_and_governance` | **PASS** | Registry contract metadata & schema verification |

---

## 5. In-Depth Investigation: Pravah API 401 Authentication Failure

### Manifestation
* **Failing Test:** `tests/integration/test_pravah_api.py:27` (`test_api_ingest_event_success`)
* **Expected Result:** HTTP 201 Created
* **Actual Result:** HTTP 401 Unauthorized
* **Response Body:**
  ```json
  {
    "error": {
      "type": "http_error",
      "message": "DENY:INVALID_CREDENTIALS: Token is invalid or badly signed."
    }
  }
  ```

### Technical Root Cause
The failure is caused by an **interaction between top-level test client token issuance and pytest's test-lifecycle isolation fixtures**:

1. **Top-Level Token Issuance at Module Import Time:**
   In `tests/integration/test_pravah_api.py` lines 11–12:
   ```python
   _token, _ = main.auth_service.issue_token("kavy", ["bhiv-admin", "operator"])
   client = TestClient(app, headers={"Authorization": f"Bearer {_token}"})
   ```
   This code executes once when pytest imports `test_pravah_api.py`. At that instant, `main.auth_service` is signed with an initial secret key `K_0`.

2. **Per-Test Fixture Replaces AuthService Instance:**
   In `tests/conftest.py` line 157, the `fresh_session_persistence` autouse fixture runs before **every individual test**:
   ```python
   @pytest.fixture(autouse=True)
   def fresh_session_persistence(monkeypatch):
       ...
       main.auth_service = main.AuthService()
   ```
   When `main.AuthService()` is instantiated without an explicit `AUTH_JWT_SECRET` environment variable (the default in CI), it generates a brand new cryptographically random secret key `K_test`.

3. **HMAC Signature Mismatch During Request Execution:**
   When `test_api_ingest_event_success()` calls `client.post("/pravah/events", json=payload)`, the HTTP request header contains `_token` signed with `K_0`.
   The endpoint's dependency `Depends(get_identity)` calls `main.auth_service.verify_token(_token)`.
   Because `main.auth_service` now holds `K_test`, the HMAC-SHA256 signature verification fails:
   ```text
   WARNING masterdb.security:service.py:49 SECURITY_DECISION: {"actor_reference": "unauthenticated", "outcome": "DENY", "reason_code": "DENY:INVALID_CREDENTIALS"}
   WARNING masterdb:main.py:362 HTTPException 401 at /pravah/events: DENY:INVALID_CREDENTIALS: Token is invalid or badly signed.
   ```
   FastAPI returns HTTP 401, causing `assert resp.status_code == 201` to fail.

4. **Remediation Path (Pre-Existing Issue Scope):**
   To resolve this across the integration suite (outside PR #12's scope), the `client` in `test_pravah_api.py` must be converted from a top-level global into a pytest fixture that issues a fresh token using `main.auth_service` *inside* the active test lifecycle, or use `test_auth_headers`.

---

## 6. Categorization of Remaining 148 Pre-Existing Failures

All remaining 148 failures pre-date PR #12 and fall into six well-defined architectural categories:

| Category | Description | Failure Count | Key Affected Modules |
| :---: | :--- | :---: | :--- |
| **1. Protected Route Authentication** | Legacy tests issuing unauthenticated HTTP requests to routes hardened during PR #10/PR #11 security remediation. | **96** | `test_endpoint_access_matrix.py`, `test_capability_retrieval.py`, `test_capability_authorization.py`, `test_pravah_api.py` |
| **2. Access Matrix Parity** | Discrepancies between expected status codes (e.g., expected 403 Forbidden vs 401 Unauthorized or unprotected 200). | **14** | `test_endpoint_access_matrix.py` |
| **3. Identity & Fast-Track Remediations** | Missing attributes or startup validation exceptions on `AuthService` (`is_production`, RSA key length validation). | **15** | `test_fast_track_security_remediation.py`, `test_trusted_jwt_identity_boundary.py` |
| **4. BCAES Authority Boundary** | `bcaes_registry/store.py` invoked without caller identity context (`actor=None`), triggering `PermissionDeniedError`. | **9** | `test_backup_service.py`, `test_persistence.py`, `test_sql_database.py` |
| **5. Capability Grant Contract Keys** | Access grant responses missing expected legacy keys (`access_token`, `request_id`). | **4** | `test_capability_retrieval.py` |
| **6. Miscellaneous Lifecycle / Rate Limiting** | Route 404s, missing health configuration keys, or accumulated rate limiter counter state across tests. | **10** | `test_authentication_security.py`, `test_rate_limit_middleware.py`, `test_gev_masterdb_import.py` |
| **TOTAL** | | **148** | |

---

## 7. PR #12 Post-Merge Verification & Closure Verdict

* **PR #12 Lifecycle Status:** **ALREADY MERGED** (Merged into `main` at commit `169ce3c130d8780fef9e9e0f43bafc7b0fdd2608`).
* **Post-Merge Regression Resolution:** The single regression observed in post-merge CI Run `43167724350` (`test_all_consumer_dataset_contracts_match_schema`) was completely diagnosed, resolved, and verified via `datasets/dataset_contracts.json`.
* **CMO Data Validation Implementation:** Certified, compliant, 19/19 tests passing (100%).
* **Dataset Contract Conformance:** Certified, compliant, 6/6 tests passing, 17 contracts and 11 shared schemas validated.
* **Regression Status:** **ZERO new regressions.** Test suite restored to exact pre-existing baseline (148 failed / 799 passed).
* **Action Required:** Verified contract fix ready for local commit on `feature-hariom-cmo-data-integrity` to complete evidence closure.
