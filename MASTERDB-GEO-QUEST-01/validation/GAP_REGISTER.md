# BHIV vNEXT MASTERDB-GEO-QUEST-01: Known-Defect & Missing-Evidence Gap Register

**Author / Candidate:** Hariom Upadhyay
**Role:** Data Quality & Ingestion Specialist
**Target Capability:** `gev.aircraft_tracking`
**Candidate Dataset:** `BHIV-GEO-QUEST-01-AIRCRAFT`
**Reviewer:** Harsha Pawar
**Platform Owner:** Kavy Changela
**Last Updated:** `2026-10-15T09:45:00Z`

---

## 1. Executive Summary

This Gap Register identifies all known defects, missing evidence, boundary constraints, and ambiguous contracts across the **Source → Clean → Validate → Classify → Register → Discover** lifecycle for the candidate aircraft dataset.
Per task instructions, **no claim is fabricated, no PASS status is assumed without reproducible evidence, and responsibilities outside the candidate data quality boundary are clearly attributed to their respective owners.**

---

## 2. Gap & Defect Register Table

| Gap ID | Category | Description | Severity | Impacted Component | Root Cause / Context | Current Status | Required Action & Responsible Owner |
|---|---|---|---|---|---|---|---|
| **GAP-01** | Platform Governance | Canonical MASTERDB Write Authority is unconfirmed | **BLOCKER** | Registration / Canonical Catalog | Candidate data is staged locally under `/geo-quest/candidates/*` with status `PENDING_AUTHORIZATION`. No canonical MasterDB UUID has been issued. | **PENDING** | **Kavy Changela / Harsha Pawar** must provide formal domain council sign-off and issue canonical dataset UUID before live promotion. |
| **GAP-02** | Telemetry Completeness | Upstream transponders occasionally omit squawk / geometric altitude | **LOW (Expected)** | Fields: `squawk_code`, `altitude_geom_ft` | 1 of 19 records (5.26%) lacks squawk code and geometric altitude due to legacy Mode S transponder operation without GNSS augmentation. | **DOCUMENTED** | Normal operational characteristic of civil airspace ADS-B. Handled gracefully as nullable in schema; downstream anomaly detectors must account for 5% missingness. |
| **GAP-03** | Spatial Coverage | Oceanic line-of-sight decay west of Mumbai coastline | **MEDIUM** | Geographic Coverage Envelope | Feeder density drops over the Arabian Sea beyond 70 nmi from coastal SDR receivers. Low-altitude aircraft may drop off radar horizon. | **DOCUMENTED** | **Hariom**: documented in limitations. Downstream consumers requiring maritime coverage must correlate with Marine AIS or satellite ADS-B. |
| **GAP-04** | Runtime Integration | Live telemetry event streaming bus unconfigured | **BLOCKER (Downstream)** | TANTRA runtime event bus | Candidate dataset provides verified point-in-time snapshot and batch normalization pipeline. Live Kafka/Pravah streaming is not configured. | **PENDING** | **Rajaryan (TANTRA)** to define runtime ingestion hook once canonical status is granted. |
| **GAP-05** | Semantic Contract | MDU schema version negotiation not confirmed against MDU registry | **MEDIUM** | MDU Contract Adapter | Local schema version is declared as `1.0.0` with strict field mapping, but formal MDU schema registry contract ID is pending. | **PENDING** | **Nupur (MDU)** to confirm semantic ontology mapping and assign canonical schema definition ID in MDU registry. |
| **GAP-06** | Test Evidence | Lack of dedicated multi-scenario negative test fixtures in repository | **RESOLVED** | Fixtures & Deterministic Validation | Previously only 1 positive live dataset existed. Comprehensive fixtures covering duplicate, malformed, stale, and inconsistent records have now been added. | **CLOSED** | **Hariom**: Created 6 deterministic failure fixtures and rule engine test suite `tests/test_geo_quest_quality_rules.py`. |

---

## 3. Boundary & Ownership Matrix

| Function | Primary Owner | Secondary / Reviewer | Candidate Responsibility (Hariom) |
|---|---|---|---|
| Synthetic & Live Data Cleansing, Normalization | **Hariom Upadhyay** | Harsha Pawar | Fully owned & executed |
| Data Dictionary & Profiling Calculations | **Hariom Upadhyay** | Harsha Pawar | Fully owned & executed |
| Deterministic Validation Rules & Exception Records | **Hariom Upadhyay** | Harsha Pawar | Fully owned & executed |
| Fixtures for Stale/Duplicate/Malformed Records | **Hariom Upadhyay** | Harsha Pawar | Fully owned & executed |
| Independent Registration/Retrieval Reconciliation | **Hariom Upadhyay** | Harsha Pawar | Fully owned & executed |
| MASTERDB Platform Architecture & Storage APIs | **Kavy Changela** | Harsha Pawar | Out of scope — consume approved endpoints only |
| MDU Semantic Contracts & Schema Registry Authority | **Nupur** | Harsha Pawar | Out of scope — consult when ambiguous |
| TANTRA Runtime Discovery & Orchestration | **Rajaryan** | Harsha Pawar | Out of scope — do not simulate live runtime |
| Final Acceptance & Combined Evidence Review | **Harsha Pawar** | — | Submit complete handover packet |
