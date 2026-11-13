# CMO Agent V2 — Corpus & Source Inventory Report

**Report Identifier:** `EVID-CMO-V2-CORPUS-001`
**Report Date:** 2026-11-12
**Assigned Specialist:** Hariom Upadhyay (MASTERDB Data Integrity Lead)
**Repository:** `bhiv-masterdb-ingestion-certification-service`
**Branch:** `feature-hariom-cmo-data-integrity`
**Scope:** Complete inventory of all CMO-related datasets, schemas, fixtures, and external production sources.

---

## 1. Executive Summary & Inventory Overview

This report provides a granular, factual accounting of every data source, fixture, schema, and reference file associated with the CMO Agent V2 Marketing Intelligence domain.

> [!IMPORTANT]
> **CRITICAL PRODUCTION DISTINCTION**
> All 9 data files and fixtures currently resident in the repository are **strictly synthetic test fixtures** generated to establish mathematical, structural, and contractual validation boundaries.
> **No live production telemetry from BIQOS or external ad platforms (Google Ads, Meta, LinkedIn, X, etc.) currently resides in this repository.** Live production ingestion remains an **unfulfilled external dependency owned by Prateek**.

---

## 2. Comprehensive Source & Corpus Inventory

| # | Source Designation | Relative File Path | Format | Record Count | Data Tier / Classification | Origin System | Synthetic vs Production | Availability | Intended Usage | Verification Status |
| :-: | :--- | :--- | :---: | :---: | :--- | :--- | :---: | :---: | :--- | :---: |
| 1 | **CMO Clean JSON Benchmark** | `datasets/cmo/cmo_marketing_sample_valid.json` | JSON | 10 records | `synthetic_verification` | Synthetic Benchmark Generator | **SYNTHETIC** | Local file | Golden benchmark, unit tests, pipeline validation | **VERIFIED** (19/19 tests pass) |
| 2 | **CMO Clean CSV Benchmark** | `datasets/cmo/cmo_marketing_sample_valid.csv` | CSV | 10 records | `synthetic_verification` | Exported from JSON benchmark | **SYNTHETIC** | Local file | Tabular ingestion, streaming CSV parser testing | **VERIFIED** |
| 3 | **CMO Dataset Metadata Contract** | `datasets/cmo/cmo_metadata.json` | JSON | 1 descriptor | `synthetic_governance` | Authored by Hariom Upadhyay | **SYNTHETIC** | Local file | Lineage tracking, capability registration contract | **VERIFIED** |
| 4 | **CMO Schema Specification** | `datasets/cmo/cmo_marketing_intelligence.schema.json` | JSON Schema (Draft 2020-12) | 1 schema (16 rules) | Governance Contract | Authored by Hariom Upadhyay | **CONTRACT** | Local file | Structural validation, type & enum boundary enforcement | **VERIFIED** (Exit 0) |
| 5 | **CMO Defect: Schema Mismatch** | `datasets/cmo/fixtures/cmo_defect_schema_mismatch.json` | JSON | 2 records | `synthetic_defect` | Synthetic Defect Generator | **SYNTHETIC DEFECT** | Local file | Negative testing: type corruption & invalid enums | **VERIFIED** (Fails closed) |
| 6 | **CMO Defect: Stale Freshness** | `datasets/cmo/fixtures/cmo_defect_stale_freshness.json` | JSON | 2 records | `synthetic_defect` | Synthetic Defect Generator | **SYNTHETIC DEFECT** | Local file | Negative testing: freshness SLA breach (>5000h) | **VERIFIED** (Fails closed) |
| 7 | **CMO Defect: Duplicate Records** | `datasets/cmo/fixtures/cmo_defect_duplicate_records.json` | JSON | 3 records | `synthetic_defect` | Synthetic Defect Generator | **SYNTHETIC DEFECT** | Local file | Negative testing: PK collisions & row duplicates | **VERIFIED** (Fails closed) |
| 8 | **CMO Defect: Missing Records** | `datasets/cmo/fixtures/cmo_defect_missing_records.json` | JSON | 2 records | `synthetic_defect` | Synthetic Defect Generator | **SYNTHETIC DEFECT** | Local file | Negative testing: nulls in mandatory metrics | **VERIFIED** (Fails closed) |
| 9 | **CMO Defect: Integrity Violations** | `datasets/cmo/fixtures/cmo_defect_integrity_violations.json` | JSON | 2 records | `synthetic_defect` | Synthetic Defect Generator | **SYNTHETIC DEFECT** | Local file | Negative testing: funnel inversions & negative spend | **VERIFIED** (Fails closed) |
| 10 | **Authoritative BIQOS Production Telemetry** | *Pending Delivery from Prateek* | Expected JSON / Parquet / SQL | UNKNOWN (0 received) | Production Telemetry | Live BIQOS Marketing Telemetry Hub | **PRODUCTION** | **UNAVAILABLE** | Target production ingestion for CMO Agent V2 | **BLOCKED** (Awaiting Prateek) |

---

## 3. Detailed Source Profiles

### 3.1. Clean Benchmark Dataset (`cmo_marketing_sample_valid.json`)
* **Path:** `datasets/cmo/cmo_marketing_sample_valid.json`
* **Size:** 6,181 bytes
* **Record Count:** Exactly 10 campaign records.
* **Schema Conformance:** 100% compliant with `cmo_marketing_intelligence.schema.json` and `datasets/dataset_contracts.json`.
* **Columns Captured (16/16):** `campaign_id`, `campaign_name`, `channel`, `impressions`, `clicks`, `conversions`, `spend_usd`, `revenue_usd`, `roas`, `cac`, `attribution_model`, `status`, `start_date`, `end_date`, `last_updated_utc`, `provenance_source`.
* **Channels Represented:** `search` (3), `social` (1), `display` (1), `email` (2), `video` (2), `affiliate` (1).
* **Attribution Models Represented:** `data_driven` (3), `linear` (2), `last_touch` (3), `first_touch` (2).
* **Aggregate Totals:**
  - Total Spend: \$54,800.00 USD
  - Total Revenue: \$234,400.00 USD
  - Aggregate ROAS: 4.28x
  - Total Impressions: 1,178,000
  - Total Clicks: 51,695
  - Total Conversions: 4,788
* **Integrity Status:** All records satisfy $Impressions \ge Clicks \ge Conversions \ge 0$, $Spend \ge 0$, and $|ROAS - \frac{Revenue}{Spend}| \le 0.1$.

### 3.2. Master Metadata Contract (`cmo_metadata.json`)
* **Path:** `datasets/cmo/cmo_metadata.json`
* **Dataset Identifier:** `ds-cmo-marketing-001`
* **Capability Binding:** `cap-cmo-marketing-intelligence` (Version `1.0.0`)
* **Governance Status:** `SYNTHETIC_VERIFIED_CANDIDATE`
* **Declared Freshness SLA:** 48 hours (Configured test threshold; pending Prateek's business confirmation).
* **Lineage Chain:** `Synthetic-CMO-Generator -> MASTERDB-Governed-Store`.

### 3.3. Defect Fixtures Suite (`datasets/cmo/fixtures/`)
All defect fixtures are isolated to verify fail-closed behavior across the 5 validation pillars:
1. `cmo_defect_schema_mismatch.json`: Corrupts numeric types (string in `spend_usd`), introduces illegal channel (`billboard`), and drops `attribution_model`.
2. `cmo_defect_stale_freshness.json`: Sets `last_updated_utc` to timestamps from year 2025 (>5000 hours old).
3. `cmo_defect_duplicate_records.json`: Injects primary key collision on `CMP-2026-Q4-001` and duplicate row hashing.
4. `cmo_defect_missing_records.json`: Contains nulls across `spend_usd`, `conversions`, and `campaign_id`.
5. `cmo_defect_integrity_violations.json`: Inverts marketing funnels ($Clicks = 120,000 > Impressions = 50,000$; $Conversions = 8,000 > Clicks = 4,000$) and injects $-\$1,500.00$ spend.

---

## 4. Production Telemetry Gap Analysis

| Requirement | Current Repository Status | Gap Description | Responsible Owner |
| :--- | :--- | :--- | :---: |
| **Authoritative Production Corpus** | NOT DELIVERED | Repository contains zero live production marketing records. | **Prateek** |
| **Authoritative Production Schema** | PROPOSED (Synthetic) | Current schema is inferred from synthetic benchmark requirements; requires Prateek's formal sign-off. | **Prateek** |
| **Production Ingestion Endpoint** | NOT DELIVERED | Ingestion API endpoints, authentication keys, and network routing are unconfigured. | **Kavy** |
| **Live Database Credentials** | FAIL-CLOSED | No live MASTERDB or PostgreSQL credentials present; all tests run on in-memory SQLite fallbacks. | **Kavy** |

---

## 5. Verification Sign-off

* **Inventory Completeness:** 100% of local files cataloged.
* **Synthetic Differentiation:** Complete. No synthetic fixture is represented as live data.
* **Lead Sign-Off:** Hariom Upadhyay (MASTERDB Data Integrity Lead) — 2026-11-12
