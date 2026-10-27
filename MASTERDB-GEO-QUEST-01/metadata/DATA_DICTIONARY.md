# BHIV vNEXT MASTERDB-GEO-QUEST-01: Data Dictionary & Field Definitions

**Dataset Identifier:** `BHIV-GEO-QUEST-01-AIRCRAFT`
**Dataset Name:** `BHIV vNEXT Normalized Aircraft Observation Dataset`
**Schema Version:** `1.0.0`
**Dataset Version:** `1.0.0-candidate`
**Coordinate Reference System:** EPSG:4326 (WGS84)
**Licensing:** Open Data Commons Open Database License (ODbL) v1.0
**Attribution Statement:** `"adsb.lol and its contributors"`
**Target Airspace:** Mumbai FIR (VABB / BOM) — `19.0760° N, 72.8777° E`, 100 nmi radius

---

## 1. Overview & Data Architecture

This Data Dictionary defines the 20 standardized attributes of the candidate governed spatial dataset `BHIV-GEO-QUEST-01-AIRCRAFT`.
Each record represents a discrete, real-world aircraft surveillance state vector captured from Mode S / ADS-B transponder broadcasts via the `adsb.lol` God's Eye View SDR aggregation feed, cleaned and normalized according to deterministic validation rules.

---

## 2. Comprehensive Field Specifications

| # | Field Name | Data Type | Nullable | Source Key (Raw) | Valid Range / Regex | Baseline Missingness | Description & Business Semantics |
|---|---|---|---|---|---|---|---|
| 1 | `aircraft_hex_id` | `string` | **No** | `hex` | `^[0-9A-F]{1,6}$` (e.g. `^[0-9A-F]{6}$`) | **0%** (19/19 present) | Unique 24-bit ICAO aircraft transponder hexadecimal address. Normalized to uppercase with leading/trailing whitespace removed. Primary entity identifier. |
| 2 | `callsign` | `string` | Yes | `flight` | `^[A-Z0-9]{1,8}$` | **0%** (19/19 present) | Radiotelephony flight identification or operator callsign (e.g., `FDX8`, `AIC6PQ`). Trimmed and uppercase. |
| 3 | `registration` | `string` | Yes | `r` | `^[A-Z0-9\-]{1,12}$` | **0%** (19/19 present) | National civil or military airframe tail registration code (e.g., `N856FD`, `VT-EXV`). Trimmed and uppercase. |
| 4 | `aircraft_type_icao` | `string` | Yes | `t` | `^[A-Z0-9]{2,4}$` | **0%** (19/19 present) | Standard 4-character ICAO aircraft type designator (e.g., `B77L` = Boeing 777F, `A20N` = Airbus A320neo, `B738` = Boeing 737-800). |
| 5 | `squawk_code` | `string` | Yes | `squawk` | `^[0-7]{4}$` | **5.26%** (1/19 missing) | 4-digit octal Secondary Surveillance Radar (SSR) transponder beacon code assigned by Air Traffic Control. Missing when transponder operates in unassigned/passive mode. |
| 6 | `emitter_category` | `string` | Yes | `category` | `^[A-C][0-7]$` | **0%** (19/19 present) | ADS-B emitter category identifying airframe wake-turbulence classification (e.g., `A3` = Large 75k-300k lbs, `A5` = Heavy >300k lbs). |
| 7 | `latitude` | `float` | **No** | `lat` | `[-90.000000, +90.000000]` | **0%** (19/19 present) | WGS84 geographic latitude in decimal degrees, normalized to 6 decimal places (~0.11m spatial resolution). |
| 8 | `longitude` | `float` | **No** | `lon` | `[-180.000000, +180.000000]` | **0%** (19/19 present) | WGS84 geographic longitude in decimal degrees, normalized to 6 decimal places. |
| 9 | `altitude_baro_ft` | `integer` | Yes | `alt_baro` | `[-2000, 85000]` | **0%** (19/19 present) | Barometric pressure altitude in feet referenced to standard 1013.25 hPa datum. Decoupled from surface state (`alt_baro: "ground"` maps to `0`). |
| 10 | `altitude_geom_ft` | `integer` | Yes | `alt_geom` | `[-2000, 85000]` | **5.26%** (1/19 missing) | Geometric GNSS altitude in feet above the WGS84 reference ellipsoid. Missing on Mode S without GNSS altitude transmission. |
| 11 | `is_on_ground` | `boolean` | **No** | `alt_baro` / `airground` | `true` or `false` | **0%** (19/19 present) | Surface operational indicator. Explicitly `true` if aircraft is taxiing, parked, or reporting surface telemetry; `false` if airborne. |
| 12 | `ground_speed_kts` | `float` | Yes | `gs` | `[0.0, 1500.0]` | **0%** (19/19 present) | Horizontal speed over ground in knots, rounded to 1 decimal place. |
| 13 | `true_track_deg` | `float` | Yes | `track` | `[0.00, 360.00]` | **5.26%** (1/19 missing) | Direction of horizontal motion over ground in degrees clockwise from True North. Missing on stationary ground targets. |
| 14 | `vertical_rate_fpm` | `integer` | Yes | `baro_rate` | `[-15000, +15000]` | **5.26%** (1/19 missing) | Rate of climb (positive) or descent (negative) in barometric feet per minute. |
| 15 | `position_age_seconds` | `float` | Yes | `seen_pos` | `[0.0, 86400.0]` | **0%** (19/19 present) | Sensor latency in seconds since the last geographic position broadcast was received. |
| 16 | `last_seen_seconds` | `float` | Yes | `seen` | `[0.0, 86400.0]` | **0%** (19/19 present) | Sensor latency in seconds since any Mode S broadcast from this airframe was detected. |
| 17 | `distance_from_center_nm` | `float` | Yes | *derived* | `[0.00, 250.00]` | **0%** (19/19 present) | Great-circle Haversine distance in nautical miles from the query center reference point (`19.0760° N, 72.8777° E`). |
| 18 | `bearing_from_center_deg` | `float` | Yes | *derived* | `[0.00, 360.00]` | **0%** (19/19 present) | Initial forward azimuth bearing from query center to aircraft location in degrees clockwise from True North. |
| 19 | `signal_rssi_db` | `float` | Yes | `rssi` | `[-50.0, +10.0]` | **0%** (19/19 present) | Receiver signal strength indicator in dBFS (decibels relative to full scale) measured at receiving SDR feeder station. |
| 20 | `provenance` | `object` | **No** | *audit engine* | Valid JSON Object conforming to provenance schema | **0%** (19/19 present) | Immutable lineage metadata block embedding source URL, query center coordinates, raw acquisition timestamp, cleaning timestamp, schema version, and pipeline stage. |

---

## 3. Provenance Object Schema

The `provenance` object embedded in every record contains:

```json
{
  "source_system": "adsb.lol",
  "source_url": "https://api.adsb.lol/v2/lat/19.0760/lon/72.8777/dist/100",
  "query_center_latitude": 19.076,
  "query_center_longitude": 72.8777,
  "query_radius_nm": 100,
  "raw_acquisition_utc": "2026-10-03T08:26:35.695048+00:00",
  "cleaning_pipeline_utc": "2026-10-15T09:44:27.232008+00:00",
  "pipeline_stage": "CLEANED_AND_NORMALIZED",
  "schema_version": "1.0.0"
}
```

---

## 4. Governance Classification & Data Sensitivity

- **Classification:** Public Open Spatial Data (ODbL v1.0).
- **PII Assessment:** **Zero Personal Identifiable Information**. Transponder telemetry relates exclusively to public radio broadcasts of aircraft navigational transponders on 1090 MHz.
- **Export Control / Defense:** Standard commercial aviation airspace monitoring; does not contain restricted tactical datalinks.
