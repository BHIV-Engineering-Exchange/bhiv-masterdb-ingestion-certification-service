# BHIV vNEXT MASTERDB-GEO-QUEST-01: Failure Scenario Execution Results

**Execution UTC:** `2026-10-15T10:23:20.400932+00:00`
**Overall Result:** **ALL 6 FAILURE SCENARIOS DETERMINISTICALLY DETECTED & QUARANTINED**

---

## 1. Scenario Summary Matrix

| Scenario ID | Scenario Name | Fixture File | Input Recs | Cleaned | Quarantined | Triggered Rules | Status | Rule Verification |
|---|---|---|---|---|---|---|---|---|
| `SCENARIO_BASELINE_CLEANED` | Candidate Cleaned Dataset Baseline | [`cleaned/aircraft_cleaned.json`](cleaned/aircraft_cleaned.json) | 19 | 19 | 0 | `NONE` | **PASS** | **PASS** |
| `SCENARIO_MISSING_PROVENANCE` | Missing Provenance Lineage | [`fixtures/invalid_missing_provenance.json`](fixtures/invalid_missing_provenance.json) | 2 | 0 | 2 | `RULE-GEO-007, RULE-GEO-006` | **DETECTED_AND_QUARANTINED** | **PASS** |
| `SCENARIO_DUPLICATE_RECORDS` | Duplicate Aircraft Hex Identifiers | [`fixtures/invalid_duplicate_records.json`](fixtures/invalid_duplicate_records.json) | 2 | 1 | 1 | `RULE-GEO-002` | **DETECTED_AND_QUARANTINED** | **PASS** |
| `SCENARIO_MALFORMED_FIELD_TYPES` | Malformed Primitive Field Types | [`fixtures/invalid_malformed_field_types.json`](fixtures/invalid_malformed_field_types.json) | 1 | 0 | 1 | `RULE-GEO-003, RULE-GEO-002, RULE-GEO-004` | **DETECTED_AND_QUARANTINED** | **PASS** |
| `SCENARIO_SCHEMA_MISMATCH` | Schema Mismatch / Null Mandatory Fields | [`fixtures/invalid_schema_mismatch.json`](fixtures/invalid_schema_mismatch.json) | 2 | 0 | 2 | `RULE-GEO-007` | **DETECTED_AND_QUARANTINED** | **PASS** |
| `SCENARIO_STALE_DATA` | Stale Latency & Negative Timing | [`fixtures/invalid_stale_data.json`](fixtures/invalid_stale_data.json) | 2 | 1 | 1 | `RULE-GEO-005` | **DETECTED_AND_QUARANTINED** | **PASS** |
| `SCENARIO_INCONSISTENT_MEASUREMENTS` | Inconsistent Kinematic Measurements | [`fixtures/invalid_inconsistent_measurements.json`](fixtures/invalid_inconsistent_measurements.json) | 2 | 0 | 2 | `RULE-GEO-004, RULE-GEO-008` | **DETECTED_AND_QUARANTINED** | **PASS** |

---

## 2. Key Findings & Proof of Integrity

1. **Mathematical Conservation:** In every scenario, $\text{Input} = \text{Cleaned} + \text{Quarantined}$ is strictly preserved.
2. **Specific Rule Matching:** Every failure scenario triggered its intended rule without false negatives.
3. **Zero Contamination:** In all negative test fixtures, zero corrupt records leaked into the cleaned output.
