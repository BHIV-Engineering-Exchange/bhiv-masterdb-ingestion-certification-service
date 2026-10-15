# BHIV vNEXT MASTERDB-GEO-QUEST-01: Rule Coverage Matrix

**Dataset ID:** `BHIV-GEO-QUEST-01-AIRCRAFT`
**Test Suite:** `tests/test_geo_quest_quality_rules.py`
**Total Rules Defined:** 10
**Total Rules Tested:** 10
**Coverage:** **100.0% Executable Test Coverage**
**Last Verified:** `2026-10-15`

---

## 1. Traceability & Rule-to-Test Mapping

Every rule defined in [`RULE_CATALOGUE.md`](RULE_CATALOGUE.md) is covered by a dedicated, deterministic pytest verification case in [`tests/test_geo_quest_quality_rules.py`](../../tests/test_geo_quest_quality_rules.py) and exercised against explicit positive or negative test fixtures.

| Rule ID | Rule Name | Target Field(s) | Severity | Test Fixture | Executable Test Function | Disposition | Test Status |
|---|---|---|---|---|---|---|---|
| **RULE-GEO-001** | Record Conservation Accounting | Entire Batch | `HARD_FAILURE` | Dynamic Batch Mismatch Fixture | `test_rule_geo_001_record_conservation` | `REJECT_BATCH` | **PASS** |
| **RULE-GEO-002** | Entity Identifier Uniqueness | `aircraft_hex_id` | `HARD_FAILURE` | [`fixtures/invalid_duplicate_records.json`](../fixtures/invalid_duplicate_records.json) | `test_rule_geo_002_duplicate_identifiers` | `QUARANTINE_DUPLICATE` | **PASS** |
| **RULE-GEO-003** | Geographic Coordinate Spatial Envelope | `latitude`, `longitude` | `HARD_FAILURE` | [`fixtures/invalid_malformed_field_types.json`](../fixtures/invalid_malformed_field_types.json) | `test_rule_geo_003_coordinate_bounds` | `QUARANTINE_RECORD` | **PASS** |
| **RULE-GEO-004** | Kinematic Range Aviation Envelopes | `ground_speed_kts`, `altitude_baro_ft`, `true_track_deg` | `HARD_FAILURE` | Kinematic Out-of-Envelope Fixture | `test_rule_geo_004_kinematic_envelopes` | `QUARANTINE_RECORD` | **PASS** |
| **RULE-GEO-005** | Temporal Latency & Freshness | `last_seen_seconds`, `position_age_seconds` | `HARD_FAILURE` (negative) / `WARNING` (stale) | [`fixtures/invalid_stale_data.json`](../fixtures/invalid_stale_data.json) | `test_rule_geo_005_temporal_integrity_and_staleness` | `QUARANTINE` / `FLAG_STALE` | **PASS** |
| **RULE-GEO-006** | Audit Lineage & Provenance Completeness | `provenance` | `HARD_FAILURE` | [`fixtures/invalid_missing_provenance.json`](../fixtures/invalid_missing_provenance.json) | `test_rule_geo_006_provenance_completeness` | `REJECT_RECORD` | **PASS** |
| **RULE-GEO-007** | Mandatory Schema Conformance & Type Safety | `aircraft_hex_id`, `latitude`, `longitude`, `is_on_ground` | `HARD_FAILURE` | [`fixtures/invalid_schema_mismatch.json`](../fixtures/invalid_schema_mismatch.json) | `test_rule_geo_007_schema_conformance` | `QUARANTINE_RECORD` | **PASS** |
| **RULE-GEO-008** | Surface State Measurement Decoupling | `is_on_ground`, `altitude_baro_ft`, `ground_speed_kts` | `HARD_FAILURE` | [`fixtures/invalid_inconsistent_measurements.json`](../fixtures/invalid_inconsistent_measurements.json) | `test_rule_geo_008_surface_measurement_consistency` | `QUARANTINE_RECORD` | **PASS** |
| **RULE-GEO-009** | Dataset Identity vs Schema Disambiguation | `dataset_id`, `schema_version` | `HARD_FAILURE` | Contract Drift Fixture | `test_rule_geo_009_dataset_identity_vs_schema_disambiguation` | `REJECT_PAYLOAD` | **PASS** |
| **RULE-GEO-010** | Open Database License Compliance | `licence`, `attribution` | `HARD_FAILURE` | Proprietary License Fixture | `test_rule_geo_010_license_compliance` | `REJECT_ASSET` | **PASS** |
| **FIXTURE-V1** | Valid Synthetic Aircraft Baseline | All 20 Attributes | `N/A` (Positive Test) | [`fixtures/valid_synthetic_aircraft.json`](../fixtures/valid_synthetic_aircraft.json) | `test_valid_synthetic_aircraft_fixture` | `ACCEPT_ALL` | **PASS** |

---

## 2. Verification Command

```powershell
pytest tests/test_geo_quest_quality_rules.py -v
```

Execution output:
```
tests/test_geo_quest_quality_rules.py::test_rule_geo_001_record_conservation PASSED
tests/test_geo_quest_quality_rules.py::test_rule_geo_002_duplicate_identifiers PASSED
tests/test_geo_quest_quality_rules.py::test_rule_geo_003_coordinate_bounds PASSED
tests/test_geo_quest_quality_rules.py::test_rule_geo_004_kinematic_envelopes PASSED
tests/test_geo_quest_quality_rules.py::test_rule_geo_005_temporal_integrity_and_staleness PASSED
tests/test_geo_quest_quality_rules.py::test_rule_geo_006_provenance_completeness PASSED
tests/test_geo_quest_quality_rules.py::test_rule_geo_007_schema_conformance PASSED
tests/test_geo_quest_quality_rules.py::test_rule_geo_008_surface_measurement_consistency PASSED
tests/test_geo_quest_quality_rules.py::test_rule_geo_009_dataset_identity_vs_schema_disambiguation PASSED
tests/test_geo_quest_quality_rules.py::test_rule_geo_010_license_compliance PASSED
tests/test_geo_quest_quality_rules.py::test_valid_synthetic_aircraft_fixture PASSED
============================= 11 passed in 0.64s ==============================
```
