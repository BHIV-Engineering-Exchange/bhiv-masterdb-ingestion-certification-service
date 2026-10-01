# E2E VERIFICATION & EMPIRICAL EVIDENCE REPORT

## EXECUTED TEST SUITE SUMMARY

```text
python -m pytest tests/ -q
394 passed, 0 failed, 35895 warnings in 97.54s (0:01:37)
```

```text
python -m pytest tests/test_real_e2e_flow.py -v
1 passed in 2.54s
```

```text
python -m pytest tests/test_fresh_session_persistence.py -v
1 passed in 1.86s
```

---

## EMPIRICAL EVIDENCE BREAKDOWN

### 1. Authentication Evidence
* **Command:** `python -m pytest tests/test_authentication_security.py -v`
* **Result:** `PASS (6 passed)`
* **Verification:**
  - Token request with invalid password returns `401 Unauthorized`.
  - Self-assignment of `["bhiv-admin"]` by non-admin actor returns `["viewer", "dashboard-viewer"]` assigned via trusted server-side mapping (`resolve_roles`).
  - Protected endpoints (`GET /databases`) without Bearer header return `401`.
  - Tampered/invalid JWT returns `401`.

### 2. RBAC & Upload Ownership Evidence
* **Command:** `python -m pytest tests/test_database_targets_api.py tests/test_database_router_service.py -v`
* **Result:** `PASS (14 passed)`
* **Verification:**
  - Ingestion without target database role (e.g. `ingest:relationaldb`) returns `403 Forbidden`.
  - Modifying or viewing Upload A by User B returns `403 Forbidden`.
  - `bhiv-admin` / `operator` role bypasses specific database restriction as designed.

### 3. Upload → Ingestion Linkage Evidence
* **Command:** `python -m pytest tests/test_real_e2e_flow.py -v`
* **Result:** `PASS (1 passed)`
* **Verification:**
  - `upload_id` propagated via `POST /ingest` resolves staged content from `upload_staging/upload-XXXX/certifiable_sample.csv`.
  - Upload lifecycle advanced through `REGISTERED -> INGESTED -> AVAILABLE`.

### 4. Actual Target Persistence Evidence
* **Command:** `python -m pytest tests/test_fresh_session_persistence.py -v`
* **Result:** `PASS (1 passed)`
* **Verification:**
  - Ingested dataset saved 5 actual CSV rows (`John Doe`, `Alice Smith`, etc.) directly into SQLite/Postgres tables (`target_datasets` & `target_dataset_records`).
  - Synthetic fallback was NOT invoked.

### 5. Fresh-Session Persistence Evidence
* **Command:** `python -m pytest tests/test_fresh_session_persistence.py -v`
* **Result:** `PASS (1 passed)`
* **Verification:**
  - Session A (`sql_store_a`, `router_a`) closed and garbage collected.
  - Session B (`sql_store_b`, `router_b`) created connecting to physical database `test_target_store.db`.
  - `router_b.get_target_dataset(TargetDatabase.RELATIONAL_DB, "fresh_session_dataset")` returned `record_count: 5`, `status: PERSISTED`.
  - `router_b.list_target_records(...)` retrieved exact records identical to input CSV.

### 6. Path Security Evidence
* **Command:** `python -m pytest tests/test_database_router_service.py -v`
* **Result:** `PASS (8 passed)`
* **Verification:**
  - `resolve_secure_path` prevents traversal out of registered roots.
  - Test temporary directories (`tmp_path / datasets`) explicitly registered using `register_allowed_root`.
