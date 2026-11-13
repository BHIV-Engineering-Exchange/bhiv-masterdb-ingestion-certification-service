# CMO Agent V2 — Rights and Authorization Report

**Report Identifier:** `EVID-CMO-V2-RIGHTS-001`
**Report Date:** 2026-11-12
**Assigned Specialist:** Hariom Upadhyay (MASTERDB Data Integrity Lead)
**Repository:** `bhiv-masterdb-ingestion-certification-service`
**Branch:** `feature-hariom-cmo-data-integrity`
**Scope:** Legal, licensing, usage permissions, consumer authorization, and privacy evaluation for CMO Marketing Intelligence.

---

## 1. Executive Summary

This report establishes the formal rights, data ownership, licensing boundaries, consumer authorization rules, and privacy restrictions governing CMO Agent V2 datasets.

> [!IMPORTANT]
> **GOVERNANCE MANDATE**
> Technical ability to query an API or read a local JSON file **does NOT constitute legal authorization or production licensing**.
> In accordance with BHIV Constitutional Governance, all external data rights must be backed by explicit institutional approvals from **Prateek (CMO Lead)**.

---

## 2. Source-by-Source Rights & Authorization Matrix

Every data source and telemetry channel is evaluated across 9 legal and governance dimensions and assigned a strict classification: `VERIFIED`, `PARTIALLY VERIFIED`, `UNKNOWN`, or `BLOCKED`.

| Source / Telemetry Channel | Data Ownership | Licensing Terms | Usage Permissions | Access Tier | Consumer Authorization | Export Permissions | Retention Policy | Privacy / PII Restrictions | Verdict | Responsible Dependency |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :---: | :---: |
| **Synthetic Clean Benchmark** (`cmo_marketing_sample_valid.json`) | BHIV Engineering | `BHIV-PROPRIETARY` (Internal Test Data) | Testing, validation, CI regression | `internal` | `biqos.cmo_agent`, `tantra.runtime_router`, `vajra.provenance_ledger` | Unrestricted within internal test runners | Ephemeral / Git-tracked | Zero PII; synthetic IDs only | **VERIFIED** | Hariom Upadhyay |
| **Synthetic CSV Benchmark** (`cmo_marketing_sample_valid.csv`) | BHIV Engineering | `BHIV-PROPRIETARY` | Tabular ingestion testing | `internal` | Authorized internal services | Unrestricted within test runners | Ephemeral | Zero PII | **VERIFIED** | Hariom Upadhyay |
| **Synthetic Defect Fixtures** (`fixtures/*.json`) | BHIV Engineering | `BHIV-PROPRIETARY` | Negative regression test execution | `internal` | Test runner only | Internal test isolation only | Git-tracked | Zero PII | **VERIFIED** | Hariom Upadhyay |
| **Authoritative BIQOS Production Telemetry** | BIQOS / Executive Division | UNKNOWN (No license agreement filed) | Marketing analytics (Pending confirmation) | `restricted` | UNKNOWN (Requires formal grant) | UNKNOWN | UNKNOWN | UNKNOWN (Potential attribution click PII) | **BLOCKED** | **Prateek** |
| **External Search Channels (Google Ads / Bing)** | External Platform / Advertiser | UNKNOWN (Terms of service / API agreement unverified) | UNKNOWN | `restricted` | NOT GRANTED | BLOCKED | UNKNOWN | GCLID / User IP tracking risks | **BLOCKED** | **Prateek** |
| **External Social Channels (Meta / LinkedIn / X)** | External Platform / Advertiser | UNKNOWN (Developer API terms unverified) | UNKNOWN | `restricted` | NOT GRANTED | BLOCKED | UNKNOWN | Ad engagement PII | **BLOCKED** | **Prateek** |
| **$30,000 LinkedIn Campaign Activation** | BIQOS Marketing | Executive Budget Approval | Execution gated | `restricted` | Executive Agent only | Forbidden without approval | Audit log permanent | Budgetary liability safeguard | **BLOCKED** (`AWAITING_APPROVAL`) | **Prateek / Executive Agent** |

---

## 3. Analysis by Rights Dimension

### 3.1. Data Ownership
* **Synthetic Artifacts:** Wholly owned by BHIV Engineering Exchange as generated internal test material.
* **Production Marketing Data:** Owned by BIQOS / Executive Agency. Prateek is the authoritative data owner who must formally grant ingestion rights to MASTERDB.

### 3.2. Licensing & Intellectual Property
* **Synthetic Benchmarks:** Declared under `BHIV-PROPRIETARY` in `datasets/cmo/cmo_metadata.json`. No third-party intellectual property or external copyright encumbrances exist.
* **Production Telemetry:** Third-party platform Terms of Service (e.g. Google Ads API Developer Terms, Meta Platform Terms) have **not been reviewed or filed** in this repository.

### 3.3. Usage Permissions & Allowed Purposes
In `datasets/dataset_contracts.json`, the capability `cap-cmo-marketing-intelligence` restricts operations to four explicitly registered purposes:
1. `marketing_intelligence`
2. `executive_dashboard`
3. `attribution_analysis`
4. `budget_optimization`
Any operation outside these four declared purposes is rejected fail-closed by MASTERDB capability governance.

### 3.4. Consumer Authorization & Domain Access Boundaries
Access is gated at the capability layer (`CapabilityRegistryService.retrieve`). In `datasets/dataset_contracts.json`, the authorized consumer set and domain boundaries are strictly delineated:
* **Allowed Domains:** `["marketing", "biqos", "executive_agent", "masterdb", "tantra", "runtime", "governance"]`
* **Authorized Consumers:**
  - `biqos.cmo_agent` (Consumer Agent)
  - `executive.biqos_dashboard` (Executive Viewer)
  - `tantra.runtime_router` (Ecosystem Routing Bus)
  - `vajra.provenance_ledger` (Cryptographic Audit Ledger)
All unlisted consumers or unauthenticated callers encounter immediate `CapabilityAccessDeniedError`.

### 3.5. Export & Egress Controls
* **Visibility:** Designated as `"visibility": "internal"` and `"classification": "synthetic"`.
* **Egress Policy:** Egress outside the BHIV internal perimeter is strictly prohibited. No public API export endpoints are enabled for CMO telemetry.

### 3.6. Data Retention & Lifecycle
* **Synthetic Test Fixtures:** Retained in version control for automated regression testing.
* **Production Data Retention Policy:** Currently **UNKNOWN**. An institutional data retention policy (e.g., 90-day rolling aggregate vs 7-year financial audit trail) has not been provided by Prateek.

### 3.7. Privacy & PII Safeguards
* **Synthetic Fixtures:** Analyzed and confirmed to contain **zero Personally Identifiable Information (PII)**. All identifiers are synthetic campaign hashes (`CMP-2026-Q4-001` through `CMP-2026-Q4-010`).
* **Production Ingestion Risk:** Live attribution telemetry often carries sensitive identifiers (e.g. click IDs, hashed email newsletter subscriber IDs, device fingerprints). Before live ingestion can be authorized, Prateek must provide an explicit PII sanitization and masking policy compliant with DPDP/GDPR regulations.

---

## 4. Special Safety Boundary: $30,000 LinkedIn Campaign

> [!CAUTION]
> **FINANCIAL GOVERNANCE & EXECUTION HOLD**
> In accordance with executive instructions and risk protocols:
> - **The $30,000 LinkedIn marketing campaign MUST NOT be activated, published, or transitioned to `ACTIVE`.**
> - **The operational status is permanently locked at `AWAITING_APPROVAL`.**
> - No automated test, ingestion script, or deployment workflow may trigger live media spend without explicit, out-of-band executive cryptographic authorization.

---

## 5. Missing Approvals & Dependencies

| Approval Needed | Impact | Responsible Owner | Target Action |
| :--- | :--- | :---: | :--- |
| **Formal Production Ingestion Authorization** | Blocks live ingestion into MASTERDB | **Prateek** | Sign off on CMO production contract and data release. |
| **Platform API Licensing & ToS Review** | Blocks connection to Google Ads / Meta APIs | **Prateek** | Verify third-party terms allow AI ingestion and caching. |
| **PII & Data Sanitization Specification** | Blocks processing of user-level attribution logs | **Prateek** | Provide masking requirements for click/device telemetry. |
| **Retention & Deprecation Schedule** | Blocks automated database pruning configuration | **Prateek** | Specify retention period for daily campaign metrics. |

---

## 6. Lead Certification

* **Evaluation Integrity:** Every rights category is supported by repository contracts or marked `UNKNOWN` / `BLOCKED`.
* **Lead Sign-Off:** Hariom Upadhyay (MASTERDB Data Integrity Lead) — 2026-11-12
