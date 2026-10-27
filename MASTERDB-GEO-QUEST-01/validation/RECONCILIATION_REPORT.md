# BHIV vNEXT MASTERDB-GEO-QUEST-01: Registration and Retrieval Reconciliation Report

**Report ID:** `RECON-GEO-QUEST-001`
**Execution Timestamp:** `2026-10-15T10:23:21.990352+00:00`
**Candidate Dataset ID:** `BHIV-GEO-QUEST-01-AIRCRAFT`
**Schema Version:** `1.0.0`
**Dataset Version:** `1.0.0-candidate`
**Evaluator:** Hariom Upadhyay (Data Quality Specialist)
**Reviewer:** Harsha Pawar

---

## 1. Executive Summary

This independent reconciliation verifies end-to-end data conservation across the **Source → Clean → Validate → Classify → Register → Discover** lifecycle.
It reconciles raw captured records against submitted, staged, registered, and retrieved counts, verifies complete provenance lineage, validates role-based authorization guards, and proves tamper-detection capabilities.

> [!IMPORTANT]
> **Governance Truth**: Candidate staging has been successfully demonstrated in the approved candidate interface (`/geo-quest/candidates/*`).
> **Actual production canonical registration has NOT been executed** and remains explicitly marked `PENDING_AUTHORIZATION`. No fake canonical IDs were invented.

---

## 2. Record Count Conservation Reconciliation

$$\text{Raw API Records (19)} = \text{Cleaned Submitted (19)} + \text{Quarantined (0)} = \text{Candidate Staged (19)} = \text{Retrieved (19)}$$

| Ingestion Lifecycle Stage | Count | Reconciled Status | Verification Evidence / Details |
|---|---|---|---|
| **1. Upstream Raw Capture** | **19** | **MATCH** | Live API response from `adsb.lol` (`raw/aircraft_raw.json`) |
| **2. Cleaned Dataset** | **19** | **MATCH** | Schema-normalized tabular records (`cleaned/aircraft_cleaned.json`) |
| **3. Quarantine Store** | **0** | **MATCH** | Zero non-conforming records in initial live capture (`cleaned/aircraft_quarantine.json`) |
| **4. Submitted to Candidate Registry** | **19** | **MATCH** | Staged via `GeoQuestCandidateService.register_candidate()` |
| **5. Registered Record Count** | **19** | **MATCH** | Stored in candidate bundle with status `PENDING_AUTHORIZATION` |
| **6. Unfiltered Query Retrieval** | **19** | **MATCH** | Full snapshot retrieval within 100 nmi radius |
| **7. Filtered Query Retrieval** | **1** | **MATCH** | Hex filter `ABE5A2` matches flight `FDX8` |

---

## 3. Provenance & Source Reference Reconciliation

- **Audit Lineage Completeness:** **100.0%** (19 / 19 records).
- **Upstream Source Endpoint:** `https://api.adsb.lol/v2/lat/19.0760/lon/72.8777/dist/100`
- **Acquisition Timestamp:** `2026-10-03T08:26:35.695048+00:00`
- **Licence Declared & Verified:** Open Data Commons Open Database License (ODbL) v1.0
- **Attribution Statement:** `"adsb.lol and its contributors"`
- **Lineage Verification Verdict:** **PASS**

---

## 4. Authorization & Security Rejections (Approved Test Environment)

Authorization enforcement was validated against the live FastAPI test client:

| Test Case | Actor Header | Endpoint Tested | Expected HTTP | Actual HTTP | Disposition |
|---|---|---|---|---|---|
| Unauthorized Registration | `x-actor: unauthorized-viewer` | `POST /geo-quest/candidates/gev.aircraft_tracking/register` | `403 Forbidden` | `403` | **PASS** |
| Unauthorized Retrieval | `x-actor: unauthorized-viewer` | `POST /geo-quest/candidates/gev.aircraft_tracking/retrieve` | `403 Forbidden` | `403` | **PASS** |
| Authorized Admin Registration | `x-actor: bhiv-admin` | `POST /geo-quest/candidates/gev.aircraft_tracking/register` | `200 OK` | `200` | **PASS** |
| Authorized Admin Retrieval | `x-actor: bhiv-admin` | `POST /geo-quest/candidates/gev.aircraft_tracking/retrieve` | `200 OK` | `200` | **PASS** |

---

## 5. Tamper Detection & Quarantine Segregation

- **Cryptographic Hash Verification:** Candidate bundles are protected by SHA-256 integrity digests over record sets.
- **Tampering Simulation:** Injected an altered callsign (`TAMPERED_RECORD`) into candidate store bundle.
- **Detection Result:** Candidate retrieve detected bundle hash mismatch and raised `CandidateRegistrationError: Candidate store integrity check failed`.
- **Verdict:** **PASS** — corrupt or tampered records cannot be retrieved by downstream consumers.

---

## 6. Distinction Between Local Mock/Staging vs Real Platform Registration

| Aspect | Local Candidate Staging | Canonical MASTERDB Platform |
|---|---|---|
| **Storage Location** | Local Candidate Store (`geo_quest_candidate_store/`) | Central Governed Database Layer |
| **Endpoint** | `/geo-quest/candidates/*` | `/packages/register`, `/tantra/datasets/register` |
| **Status** | `PENDING_AUTHORIZATION` | `ACTIVE / CANONICAL` |
| **Discoverability** | `discoverable: false` | `discoverable: true` |
| **Canonical Flag** | `canonical: false` | `canonical: true` |
| **Authority** | Validated Data Candidate | Requires Data Steward Sign-off (Harsha / Kavy) |
