# BHIV vNEXT MASTERDB-GEO-QUEST-01: Exception Register

**Generated UTC:** `2026-10-15T10:23:20.400932+00:00`
**Dataset ID:** `BHIV-GEO-QUEST-01-AIRCRAFT`
**Total Exceptions:** 20
- **Hard Failures (Quarantined/Rejected):** 18
- **Warnings (Flagged/Retained):** 2

---

## 1. Exception Principles

- **No Silent Dropping:** Records failing deterministic validation are never deleted or rewritten silently.
- **Quarantine Segregation:** Severe violations are isolated in quarantine with explicit reasons.
- **Audit Trail:** Every exception captures rule ID, field name, actual value, expected condition, and disposition.

---

## 2. Master Exception Log

| Exception ID | Rule ID | Record ID | Target Field | Severity | Disposition | Message / Reason |
|---|---|---|---|---|---|---|
| `EXC-ERR-0001` | **RULE-GEO-007** | `8005A4` | `provenance` | **HARD_FAILURE** | `QUARANTINED` | Mandatory schema attribute 'provenance' is missing or null |
| `EXC-ERR-0002` | **RULE-GEO-006** | `8005A4` | `provenance` | **HARD_FAILURE** | `QUARANTINED` | Missing audit provenance block in record |
| `EXC-ERR-0003` | **RULE-GEO-006** | `8005A5` | `provenance.source_url` | **HARD_FAILURE** | `QUARANTINED` | Provenance missing source_url |
| `EXC-ERR-0004` | **RULE-GEO-006** | `8005A5` | `provenance.raw_acquisition_utc` | **HARD_FAILURE** | `QUARANTINED` | Provenance missing raw_acquisition_utc |
| `EXC-ERR-0001` | **RULE-GEO-002** | `8005A6` | `aircraft_hex_id` | **HARD_FAILURE** | `QUARANTINED` | Duplicate aircraft hex address detected: '8005A6' |
| `EXC-ERR-0001` | **RULE-GEO-002** | `NOT_A_VALID_HEX_LONGER_THAN_6_CHARS_!` | `aircraft_hex_id` | **HARD_FAILURE** | `QUARANTINED` | Invalid Mode S hex address format: 'NOT_A_VALID_HEX_LONGER_THAN_6_CHARS_!' |
| `EXC-ERR-0002` | **RULE-GEO-003** | `NOT_A_VALID_HEX_LONGER_THAN_6_CHARS_!` | `latitude` | **HARD_FAILURE** | `QUARANTINED` | Latitude 'nineteen_degrees_north' is not a valid numeric float |
| `EXC-ERR-0003` | **RULE-GEO-004** | `NOT_A_VALID_HEX_LONGER_THAN_6_CHARS_!` | `ground_speed_kts` | **HARD_FAILURE** | `QUARANTINED` | Ground speed 'fast' is non-numeric |
| `EXC-ERR-0004` | **RULE-GEO-004** | `NOT_A_VALID_HEX_LONGER_THAN_6_CHARS_!` | `altitude_baro_ft` | **HARD_FAILURE** | `QUARANTINED` | Barometric altitude '[35000]' is malformed or non-numeric |
| `EXC-ERR-0001` | **RULE-GEO-007** | `INDEX_0` | `aircraft_hex_id` | **HARD_FAILURE** | `QUARANTINED` | Mandatory schema attribute 'aircraft_hex_id' is missing or null |
| `EXC-ERR-0002` | **RULE-GEO-007** | `INDEX_0` | `latitude` | **HARD_FAILURE** | `QUARANTINED` | Mandatory schema attribute 'latitude' is missing or null |
| `EXC-ERR-0003` | **RULE-GEO-007** | `INDEX_0` | `longitude` | **HARD_FAILURE** | `QUARANTINED` | Mandatory schema attribute 'longitude' is missing or null |
| `EXC-ERR-0004` | **RULE-GEO-007** | `INDEX_1` | `aircraft_hex_id` | **HARD_FAILURE** | `QUARANTINED` | Mandatory schema attribute 'aircraft_hex_id' is missing or null |
| `EXC-ERR-0001` | **RULE-GEO-005** | `8005A7` | `last_seen_seconds` | **HARD_FAILURE** | `QUARANTINED` | Negative sensor latency -5.2s indicates clock skew or corrupted timing |
| `EXC-ERR-0002` | **RULE-GEO-005** | `8005A7` | `position_age_seconds` | **HARD_FAILURE** | `QUARANTINED` | Negative sensor latency -1.0s indicates clock skew or corrupted timing |
| `EXC-WARN-0003` | **RULE-GEO-005** | `8005A8` | `last_seen_seconds` | **WARNING** | `FLAGGED_STALE` | Telemetry latency 650.0s exceeds 300s freshness threshold; record flagged as STALE |
| `EXC-WARN-0004` | **RULE-GEO-005** | `8005A8` | `position_age_seconds` | **WARNING** | `FLAGGED_STALE` | Telemetry latency 620.0s exceeds 300s freshness threshold; record flagged as STALE |
| `EXC-ERR-0001` | **RULE-GEO-008** | `8005A9` | `altitude_baro_ft` | **HARD_FAILURE** | `QUARANTINED` | Contradictory state: aircraft flagged as on ground but reporting 35000.0 ft altitude |
| `EXC-ERR-0002` | **RULE-GEO-008** | `8005A9` | `ground_speed_kts` | **HARD_FAILURE** | `QUARANTINED` | Contradictory state: aircraft flagged as on ground but reporting 450.0 kts speed |
| `EXC-ERR-0003` | **RULE-GEO-004** | `8005AA` | `ground_speed_kts` | **HARD_FAILURE** | `QUARANTINED` | Ground speed 2500.0 kts exceeds physical civil/military aviation envelope |
