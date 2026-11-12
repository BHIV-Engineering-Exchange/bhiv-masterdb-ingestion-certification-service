# CMO Agent V2 — Temporal Freshness & Staleness Evaluation Report

**Report Identifier:** `EVID-CMO-V2-FRESH-001`
**Report Date:** 2026-11-12
**Assigned Specialist:** Hariom Upadhyay (MASTERDB Data Integrity Lead)
**Repository:** `bhiv-masterdb-ingestion-certification-service`
**Branch:** `feature-hariom-cmo-data-integrity`
**Scope:** Technical evaluation of temporal validation logic, staleness detection, clock-drift safeguards, and business SLA boundaries.

---

## 1. Executive Summary & Critical Freshness Distinction

Freshness validation guarantees that the CMO Agent never bases high-stakes budgetary allocations or attribution models on obsolete campaign telemetry.

> [!IMPORTANT]
> **GOVERNANCE & SLA BOUNDARY NOTICE**
> - **Configured Test Threshold:** The validation service defaults to **48 hours** as a functional benchmark parameter for automated unit and integration tests.
> - **Approved Business SLA:** Currently **UNKNOWN**. The formal, authoritative business freshness SLA for live CMO operations has **NOT been confirmed by Prateek**.
> - Under no circumstances should the 48-hour test configuration be treated as the finalized production SLA.

---

## 2. Five-Way Freshness Separation Framework

To ensure operational clarity, five distinct aspects of freshness are explicitly decoupled:

```
+---------------------------------------------------------------------------------------+
| 1. Configured Test Threshold:       48 hours (parameter in test suite)                |
| 2. Approved Business SLA:           UNKNOWN (pending formal decision by Prateek)     |
| 3. Observed Source Freshness:       Static synthetic snapshot (stamped 2026-11-06)   |
| 4. Runtime Freshness Validation:    Fully implemented & verified with UTC anchors     |
| 5. Production Freshness Evidence:   NONE (zero live telemetry feeds connected)       |
+---------------------------------------------------------------------------------------+
```

| Freshness Aspect | Value / State | Mechanism / Source | Authority | Status |
| :--- | :---: | :--- | :---: | :---: |
| **Configured Test Threshold** | **48.0 Hours** | `CMODataValidationService(max_freshness_hours=48)` | Code Parameter | **IMPLEMENTED** |
| **Approved Business SLA** | **UNKNOWN** | Formal SLA policy document required from CMO Lead | **Prateek** | **AWAITING DECISION** |
| **Observed Synthetic Freshness** | ~3.5 to 6.5 Hours | Timestamps in `cmo_marketing_sample_valid.json` relative to synthetic snapshot date (`2026-11-06T12:00:00Z`) | Test Data Generator | **VERIFIED (Synthetic)** |
| **Runtime Freshness Validation** | Active | Dynamic comparison against `datetime.now(timezone.utc)` or explicit `as_of_utc` | Validation Service | **VERIFIED** (100% test pass) |
| **Production Freshness Evidence** | **0.0%** | Requires live production ingestion stream from BIQOS | Infrastructure | **UNAVAILABLE** |

---

## 3. Freshness Engine Implementation Details

The freshness validation logic resides in `services/cmo_data_validation_service.py:145–201` (`validate_freshness`).

### 3.1. Parsing & Normalization
* Reads the mandatory ISO 8601 string `last_updated_utc` from every row.
* Normalizes UTC representations (converting `Z` suffix to `+00:00` and attaching `timezone.utc` if missing).
* Malformed timestamps immediately fail with descriptive error payloads.

### 3.2. Future Timestamp & Clock-Drift Safeguard
* To prevent intentional timestamp spoofing or clock-drift errors, any record where $t_{\text{record}} > t_{\text{now}} + 5\text{ minutes}$ is flagged as:
  `"Timestamp is in the future"`
* Tested and verified in `tests/test_cmo_data_validation.py::test_freshness_detects_future_timestamps`.

### 3.3. Staleness Computation & Rejection
* Age is computed as:
  $$\text{age\_hours} = \frac{(t_{\text{now}} - t_{\text{record}}).\text{total\_seconds}()}{3600.0}$$
* If $\text{age\_hours} > \text{max\_freshness\_hours}$, the record is flagged:
  `"Data stale: record age Xh exceeds SLA threshold Yh"`
* The pillar score is calculated as clean records divided by total records:
  $$\text{score} = \frac{\text{clean\_records}}{\text{total\_records}} \times 100.0$$

### 3.4. Anti-Masking Regression Protection
* **Vulnerability Mitigated:** In earlier revisions, if a caller passed a stale dataset alongside a historical `metadata` object (e.g. `metadata.created_at_utc = "2026-11-06T09:00:00Z"`), the engine risked comparing stale records against the historical creation timestamp instead of current wall-clock time, allowing stale data to masquerade as fresh.
* **Remediation Implemented:**
  In `CMODataValidationService.validate_cmo_data_slice()` (lines 393–402):
  ```python
  ref_time = as_of_utc or datetime.now(timezone.utc)
  ```
  The engine enforces that normal runtime validation strictly defaults to `datetime.now(timezone.utc)`. An explicit `as_of_utc` parameter is accepted **only** when passed by reproducible test fixtures.
* **Test Verification:**
  - `test_freshness_regression_metadata_timestamp_cannot_mask_staleness` passes.
  - `test_freshness_runtime_default_uses_current_utc` passes.

---

## 4. Test Execution & Evidence

All 5 dedicated freshness unit tests in `tests/test_cmo_data_validation.py` pass cleanly:

| Test Name | Test Case Scenario | Observed Result | Status |
| :--- | :--- | :--- | :---: |
| `test_freshness_passes_on_recent_records` | Clean records evaluated against synthetic snapshot anchor (`2026-11-06T12:00:00Z`). | Age 3.5h–6.5h $\le$ 48h; Score `100.0`. | **PASS** |
| `test_freshness_detects_stale_records` | Defect fixture with records from 2025. | Age $>5000$h; 2 violations; Score `0.0`. | **PASS** |
| `test_freshness_detects_future_timestamps` | Injected timestamp 1 hour in the future. | Flagged as future timestamp; Score `0.0`. | **PASS** |
| `test_freshness_regression_metadata_timestamp_cannot_mask_staleness` | Stale records submitted with historical metadata timestamp. | Evaluated against `now()`; Stale records correctly rejected. | **PASS** |
| `test_freshness_runtime_default_uses_current_utc` | Omission of `as_of_utc` in runtime call. | Automatically anchors to live UTC wall clock. | **PASS** |

---

## 5. Outstanding Freshness Dependencies

1. **Prateek (CMO Lead):**
   - Formal confirmation of the approved business freshness SLA (e.g. 1 hour, 6 hours, 24 hours, or 48 hours) based on campaign pacing and ad platform sync frequency.
   - Once confirmed, `max_freshness_hours` in `services/cmo_data_validation_service.py` and `freshness_sla_hours` in `datasets/cmo/cmo_metadata.json` will be updated to match the authoritative business decision.

---

## 6. Lead Certification

* **Evaluation Integrity:** Rigorously separated test configuration from unverified business claims.
* **Lead Sign-Off:** Hariom Upadhyay (MASTERDB Data Integrity Lead) — 2026-11-12
