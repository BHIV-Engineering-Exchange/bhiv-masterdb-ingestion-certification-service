# CMO Marketing Intelligence Benchmark Dataset

> [!IMPORTANT]
> **SYNTHETIC BENCHMARK DATASET NOTICE**  
> All files in this directory (`cmo_marketing_sample_valid.csv`, `cmo_marketing_sample_valid.json`, `cmo_metadata.json`, and all fixtures in `fixtures/`) are **strictly synthetic test fixtures** generated for data integrity testing, schema conformance, and certification pipeline verification.  
> **These files do NOT contain or represent actual BIQOS production marketing telemetry records.**

---

## 1. Dataset Overview

* **Dataset ID:** `ds-cmo-marketing-001`
* **Capability ID:** `cap-cmo-marketing-intelligence`
* **Data Tier:** `synthetic_verification`
* **Synthetic Marker:** `SYNTHETIC_DATASET_BENCHMARK_FIXTURE`
* **Associated Data Files:**
  * [`cmo_marketing_sample_valid.csv`](./cmo_marketing_sample_valid.csv) — CSV representation of the 10 clean benchmark records
  * [`cmo_marketing_sample_valid.json`](./cmo_marketing_sample_valid.json) — JSON payload containing top-level synthetic metadata and the 10 clean records
  * [`cmo_metadata.json`](./cmo_metadata.json) — Master dataset descriptor and governance metadata contract
  * [`cmo_marketing_intelligence.schema.json`](./cmo_marketing_intelligence.schema.json) — JSON Schema Draft 2020-12 contract

---

## 2. Schema Specification & Column Definitions

The CSV and JSON datasets conform strictly to the following 16 mandatory fields:

| Column / Field | Type | Required | Allowed Enums / Constraints | Description |
| :--- | :--- | :---: | :--- | :--- |
| `campaign_id` | string | Yes | Regex: `^CMP-[0-9]{4}-[A-Z0-9]+-[0-9]{3,}$` | Immutable campaign identifier (e.g., `CMP-2026-Q4-001`). |
| `campaign_name` | string | Yes | 3 to 128 characters | Human-readable campaign designation. |
| `channel` | string | Yes | `search`, `social`, `email`, `display`, `affiliate`, `video` | Marketing delivery channel. |
| `impressions` | integer | Yes | $\ge 0$ | Ad impressions served. |
| `clicks` | integer | Yes | $\ge 0$, $\le \text{impressions}$ | User click engagements. |
| `conversions` | integer | Yes | $\ge 0$, $\le \text{clicks}$ | Actionable conversion events. |
| `spend_usd` | number | Yes | $\ge 0.0$ | Media spend in US dollars. |
| `revenue_usd` | number | Yes | $\ge 0.0$ | Attributed revenue in US dollars. |
| `roas` | number | Yes | $\ge 0.0$, matches $\frac{\text{revenue}}{\text{spend}}$ ($\pm 0.1$) | Return on Ad Spend. |
| `cac` | number | Yes | $\ge 0.0$ | Customer Acquisition Cost. |
| `attribution_model` | string | Yes | `last_touch`, `first_touch`, `linear`, `data_driven` | Attribution calculation model applied. |
| `status` | string | Yes | `ACTIVE`, `COMPLETED`, `PAUSED`, `SCHEDULED` | Lifecycle operational status. |
| `start_date` | string | Yes | ISO 8601 Date (`YYYY-MM-DD`) | Campaign activation date. |
| `end_date` | string | Yes | ISO 8601 Date (`YYYY-MM-DD`) | Campaign scheduled end date. |
| `last_updated_utc` | string | Yes | ISO 8601 UTC Date-Time (`YYYY-MM-DDTHH:MM:SSZ`) | Record telemetry observation timestamp (Freshness SLA: $\le 48\text{h}$). |
| `provenance_source` | string | Yes | Non-empty string | Ingestion origin identifier (e.g., `BIQOS-Marketing-Hub`). |

---

## 3. CSV Dataset Specifics

File: `cmo_marketing_sample_valid.csv`
- Header row contains the exact 16 schema column names listed above.
- Followed by 10 verified synthetic campaign rows.
- Used for tabular ingestion and CSV stream verification.
- Verified by: `test_cmo_data_validation.py` and `services/cmo_data_validation_service.py`.

---

## 4. Synthetic Defect Fixtures (`fixtures/`)

To guarantee strict regression testing and boundary verification, 5 isolated defect fixtures are maintained in `fixtures/`:

1. `cmo_defect_schema_mismatch.json` — Violates types (string in `spend_usd`), invalid channel enum, and missing `attribution_model`.
2. `cmo_defect_stale_freshness.json` — Violates the 48-hour freshness SLA (`last_updated_utc` $> 5000\text{h}$ old).
3. `cmo_defect_duplicate_records.json` — Contains primary key collisions on `campaign_id` and exact row-hash duplication.
4. `cmo_defect_missing_records.json` — Contains nulls across mandatory metrics (`spend_usd`, `campaign_id`, `conversions`).
5. `cmo_defect_integrity_violations.json` — Violates marketing funnels ($Clicks > Impressions$, $Conversions > Clicks$) and contains negative spend/revenue.
