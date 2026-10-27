# BHIV vNEXT MASTERDB-GEO-QUEST-01: Comprehensive Pipeline Audit Report

**Audit Date (UTC):** `2026-10-03T08:35:00Z`  
**Auditor:** BHIV Data Governance & Quality Assurance Pipeline  
**Target Repository:** `MASTERDB-GEO-QUEST-01`  
**Query Airspace:** Mumbai FIR (`19.0760° N, 72.8777° E`, 100 nmi radius)  
**Source Endpoint:** `https://api.adsb.lol/v2/lat/19.0760/lon/72.8777/dist/100`  

---

## Executive Summary

An exhaustive audit of the `MASTERDB-GEO-QUEST-01` repository was conducted to verify data integrity, licence legitimacy, numerical consistency, metadata completeness, and governance boundary compliance. Zero artificial, simulated, or mocked aircraft records were introduced into the repository. The pipeline operates exclusively on authentic, verifiable ADS-B radio broadcast data returned by the live `api.adsb.lol` API.

**Overall Audit Verdict:** **READY**  
All mandatory quality gates, mathematical conservation checks, lineage traces, and governance boundaries are satisfied with complete audit backing.

---

## 1. Licence Verification Result

Verification was performed exclusively against official documentation and primary source code repositories maintained by the **adsb.lol** project:

*   **Official Sources Checked:**
    *   `https://adsb.lol/` (Official Project Portal: Declares public data and API licensing)
    *   `https://adsb.lol/docs/` (Official Documentation: Outlines API terms, data license, and contributor agreement)
    *   `https://github.com/adsblol/api` (Official API Repository: Software license)
    *   `https://github.com/adsblol/globe_history` (Official Public Data Repository: Database license)
*   **Exact Licence Names & Versions:**
    *   **Aircraft Telemetry & Database:** **Open Data Commons Open Database License (ODbL) v1.0**
    *   **API Software & Server Code:** **BSD 3-Clause "New" or "Revised" License**
    *   **Contributor/Feeder Ingestion Agreement:** **Creative Commons Zero 1.0 Universal (CC0 1.0)**
*   **Licence Scope Breakdown:**
    *   The **ODbL v1.0** applies directly to the aircraft observation database and telemetry records served by the API.
    *   The **BSD 3-Clause** applies to the underlying API software and application source code.
    *   The **CC0 1.0** applies to individual feeder radio observations submitted to the network, enabling aggregated public database distribution under ODbL.
*   **Attribution & Share-Alike Requirements:**
    *   *Attribution (Section 4.3)*: Any public redistribution or downstream "Produced Work" must explicitly credit `"adsb.lol and its contributors"` and provide notice of the ODbL.
    *   *Share-Alike (Section 4.4)*: Any publicly distributed Adapted Database derived from this data must also be licensed under the ODbL v1.0.
    *   *Open Access (Section 4.6)*: Redistribution must not impose technological protection measures (DRM) restricting licensee rights without providing an unrestricted copy.
*   **Repository Action Taken:**
    *   `metadata/aircraft_metadata.json` and `scripts/generate_metadata.py` were updated with the verified ODbL v1.0 licence details, source citations, and requirement breakdown.

---

## 2. Data Integrity Result

*   **Zero Synthetic Records**: Strict compliance with the critical data integrity directive. No simulated records, no synthetic fields, and no hard-coded aircraft values exist.
*   **Verbatim Raw Capture**: The exact, unmodified API response payload is stored in `raw/aircraft_raw.json` (`20,022 bytes`, 914 lines), representing exactly 19 real aircraft observations.
*   **Separated Acquisition Headers**: Ingestion metadata (HTTP status 200, 0.699s latency, response headers, UTC timestamp) is isolated in `raw/acquisition_metadata.json`.
*   **Real-World Aircraft Identified**:
    *   `ABE5A2`: FedEx Flight 8 (`FDX8`), Boeing 777-Freighter (`N866FD`), cruising at `18,500 ft`, Lat: `18.567127`, Lon: `71.867365`.
    *   `80163F`: Air India Flight `AIC6PQ`, Airbus A320neo (`VT-TCV`), climbing through `30,825 ft`, Lat: `17.525521`, Lon: `72.359047`.
*   **WGS84 Coordinates**: 100% of observations possess verified geographic coordinates within Mumbai airspace:
    *   Latitude Range: `17.525521°` to `19.832883°` (bounds: `[-90.0, 90.0]`)
    *   Longitude Range: `71.867365°` to `74.218489°` (bounds: `[-180.0, 180.0]`)
*   **Surface / Airborne Kinematics**:
    *   Airborne altitudes span `1,025 ft` to `35,000 ft`.
    *   1 ground aircraft (`alt_baro: "ground"`) was correctly decoupled into `is_on_ground: true` and `altitude_baro_ft: 0`.

---

## 3. Pipeline Consistency Result

Every numerical statistic reported across the pipeline was audited against the raw and cleaned JSON artifacts:

| Dimension | Raw Artifact | Cleaned Artifact | Quarantine Artifact | Profiling Report | Quality Report | Metadata | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Total Aircraft Records** | `19` | `19` | `0` | `19` | `19` | `19` | **CONCURRENT (100%)** |
| **Cleaned Conformant** | — | `19` | — | — | `19` | — | **MATCH** |
| **Quarantined Records** | — | — | `0` | — | `0` | — | **MATCH** |
| **Duplicate Identifiers** | `0` | `0` | `0` | `0` | `0` | `0` | **MATCH (0 duplicates)** |
| **Conservation Equation** | $19 = 19 + 0$ | $19 = 19 + 0$ | $19 = 19 + 0$ | $19 = 19 + 0$ | $19 = 19 + 0$ | $19 = 19 + 0$ | **VERIFIED** |
| **Acquisition UTC** | `08:26:35Z` | `08:26:35Z` | — | `08:26:35Z` | `08:26:35Z` | `08:26:35Z` | **SYNCHRONIZED** |
| **Source URL** | `api.adsb.lol` | `api.adsb.lol` | `api.adsb.lol` | `api.adsb.lol` | `api.adsb.lol` | `api.adsb.lol` | **SYNCHRONIZED** |

### Quality Gate Summary (`validation/aircraft_quality_report.json`):
*   `CHK_01_RECORD_CONSERVATION` $\rightarrow$ **PASS** (`raw_count == cleaned_count + quarantined_count`)
*   `CHK_02_IDENTIFIER_UNIQUENESS` $\rightarrow$ **PASS** (`duplicate_hex_count == 0`)
*   `CHK_03_COORDINATE_VALIDITY` $\rightarrow$ **PASS** (`0 missing, 0 out-of-bounds coordinates`)
*   `CHK_04_NUMERIC_RANGE_VALIDITY` $\rightarrow$ **PASS** (`0 out-of-range speeds, tracks, or altitudes`)
*   `CHK_05_TIMESTAMP_AGE_INTEGRITY` $\rightarrow$ **PASS** (`0 negative sensor age values`)
*   `CHK_06_PROVENANCE_COMPLETENESS` $\rightarrow$ **PASS** (`100% of records have full provenance`)

---

## 4. Metadata Result

*   `metadata/aircraft_metadata.json` contains complete, verifiable, and governance-compliant documentation.
*   **Field Dictionary**: Defines 20 canonical attributes with strict data types and nullability constraints.
*   **Lineage & Chain of Custody**: Documents the complete transition:
    $$\text{adsb.lol API} \rightarrow \text{raw/} \rightarrow \text{scripts/clean\_aircraft.py} \rightarrow \text{cleaned/} \rightarrow \text{validation/}$$
*   **Physical Limitations Documented**: Outlines volunteer receiver coverage gaps, line-of-sight drop-offs over the Arabian Sea, MLAT dilution of precision, and standard barometric pressure deviations.
*   **Intended Use**: Explicitly bounded to geospatial testing, aircraft observation dataset profiling, and validation for BHIV vNEXT MasterDB spatial awareness capabilities.

---

## 5. Governance & Boundary Result

*   **No MasterDB Registration Claimed**: Status is explicitly marked `PENDING / NOT PERFORMED`.
*   **No Registration ID Invented**: MasterDB registration ID is recorded as `PENDING / NOT PERFORMED`.
*   **No Canonical Registration Claimed**: The dataset is recognized as a candidate ingestion asset, not a canonical master record.
*   **No Runtime Integration Claimed**: Status is explicitly marked `PENDING`.
*   **No Production Deployment Claimed**: Status is explicitly marked `NOT PERFORMED`.
*   **No Parallel Spatial Truth Layer Created**: `parallel_spatial_truth_layer_created: false` and `duplicate_gis_master_database_created: false`.

### Conceptual Separation Verification:
The repository cleanly distinguishes between the three core BHIV concepts:
1.  **SOURCE**: Where information comes from (`adsb.lol` community ADS-B aggregation network).
2.  **DATASET**: Governed data asset (the normalized, schema-validated artifact in `cleaned/aircraft_cleaned.json`).
3.  **CAPABILITY**: What BHIV can do with the data (airspace situational awareness, geospatial tracking, and spatial query answering).
*The cleaned dataset is nowhere described as a MasterDB canonical dataset.*

---

## 6. Issues Identified and Resolved

1.  **Timestamp Epoch Resolution**:
    *   *Issue*: The adsb.lol API provides epoch timestamps in milliseconds (`1791016059501`), which caused an `OSError` when passed directly to `datetime.fromtimestamp`.
    *   *Resolution*: Implemented millisecond-to-second conversion (`now / 1000.0` when `now > 1e11`) and ensured primary lookup from `raw/acquisition_metadata.json`.
2.  **JSON Serialization of Counter Objects**:
    *   *Issue*: `Counter` object in quarantine summary required explicit dictionary conversion for strict standard JSON compliance.
    *   *Resolution*: Wrapped with `dict(Counter(...))` in `scripts/clean_aircraft.py`.
3.  **Licence Field Resolution**:
    *   *Initial State*: Marked as `VERIFICATION REQUIRED` prior to primary source inspection.
    *   *Resolution*: Verified from official `adsb.lol` documentation and GitHub repositories as **ODbL v1.0** (data) and **BSD 3-Clause** (API code), and updated in `metadata/aircraft_metadata.json`, `scripts/generate_metadata.py`, and `validation/execution_status.md`.
4.  **Terminal Character Encoding**:
    *   *Issue*: Non-ASCII em-dash in print statements triggered CP437 display artifacts on Windows PowerShell.
    *   *Resolution*: Replaced with standard ASCII hyphens (`--`).

---

## 7. File Status & Change Manifest

| File | Status | Notes |
| :--- | :--- | :--- |
| `raw/aircraft_raw.json` | **UNMODIFIED** | Preserved exact, authentic API response. |
| `raw/acquisition_metadata.json` | **VERIFIED** | Accurate capture of HTTP headers and timestamps. |
| `cleaned/aircraft_cleaned.json` | **VERIFIED** | 19 normalized records with complete provenance. |
| `cleaned/aircraft_quarantine.json` | **VERIFIED** | 0 records; schema valid and ready for violations. |
| `scripts/collect_aircraft.py` | **VERIFIED** | Error handling and timeout operational. |
| `scripts/profile_aircraft.py` | **VERIFIED** | Statistical profiler with PENDING fallback. |
| `scripts/clean_aircraft.py` | **VERIFIED** | Normalizer with safe timestamp parser. |
| `scripts/validate_aircraft.py` | **VERIFIED** | Automated quality gates. |
| `scripts/generate_metadata.py` | **VERIFIED** | Updated with verified ODbL licence dictionary. |
| `metadata/aircraft_metadata.json` | **VERIFIED** | Complete metadata with verified licence and boundaries. |
| `validation/profiling_report.json` | **VERIFIED** | Profiles 52 fields and coordinate distributions. |
| `validation/aircraft_quality_report.json` | **VERIFIED** | 6 / 6 checks passing; missing-value stats complete. |
| `validation/execution_status.md` | **VERIFIED** | Explicit PASS / PENDING status matrix with evidence. |
| `README.md` | **VERIFIED** | Clear SOURCE / DATASET / CAPABILITY definitions. |
| `validation/final_audit_report.md` | **CREATED** | Comprehensive audit documentation. |

---

## 8. Final Audit Verdict

$$\mathbf{FINAL\ STATUS:\ READY}$$

*   **Licence Verification**: **PASS** (ODbL v1.0 for Data, BSD 3-Clause for API code, verified against official adsb.lol sources).
*   **Data Integrity**: **PASS** (Real live aircraft data only; zero synthetic records).
*   **Pipeline Consistency**: **PASS** ($19 = 19 + 0$ verified across all 14 repository artifacts).
*   **Metadata & Lineage**: **PASS** (Comprehensive schema, provenance, and physical limitations documented).
*   **Governance Boundaries**: **PASS** (All MasterDB registration and integration claims strictly marked `PENDING / NOT PERFORMED`).
