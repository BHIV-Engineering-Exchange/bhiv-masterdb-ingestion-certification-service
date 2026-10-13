#!/usr/bin/env python3
"""
BHIV vNEXT MASTERDB-GEO-QUEST-01: Data Cleaning and Normalization Script
Operates ONLY on the real raw API response (raw/aircraft_raw.json).

CRITICAL DATA INTEGRITY RULE:
- Never modifies the raw file.
- If no real raw data exists, DO NOT create fake cleaned records or fake quarantine records.
- Identifies invalid records and quarantines them with explicit violation reasons.
- Preserves aircraft identifiers and source provenance.
- Normalizes text whitespace, field names, and numeric fields.
"""

import sys
import os
import json
import argparse
import re
from datetime import datetime, timezone
from collections import Counter

def is_valid_hex_id(hex_str: str) -> bool:
    """Validate 24-bit ICAO aircraft hex address (1-6 hex chars, typically 6)."""
    if not hex_str or not isinstance(hex_str, str):
        return False
    hex_str = hex_str.strip()
    return bool(re.fullmatch(r"^[0-9a-fA-F]{1,6}$", hex_str))

def clean_and_normalize_dataset(
    raw_file_path: str,
    meta_file_path: str,
    cleaned_output_path: str,
    quarantine_output_path: str
) -> dict:
    """
    Clean and normalize raw aircraft dataset.
    Writes outputs ONLY if real raw data exists.
    """
    print("=" * 70)
    print("BHIV vNEXT MASTERDB-GEO-QUEST-01: CLEANING AND NORMALIZATION")
    print("=" * 70)
    print(f"Target Raw File:        {raw_file_path}")
    print(f"Cleaned Output Path:    {cleaned_output_path}")
    print(f"Quarantine Output Path: {quarantine_output_path}")
    print("-" * 70)

    # 1. Integrity check: file existence
    if not os.path.exists(raw_file_path) or os.path.getsize(raw_file_path) == 0:
        print("LIVE DATA STATUS: PENDING")
        print(f"[REASON] Raw data file '{raw_file_path}' does not exist or is empty.")
        print("[RULE] No fake cleaned records or fake quarantine records will be created.")
        print("=" * 70)
        return {"status": "PENDING", "reason": "Raw data file does not exist"}

    try:
        with open(raw_file_path, "r", encoding="utf-8") as f:
            raw_payload = json.load(f)
    except Exception as e:
        print("LIVE DATA STATUS: PENDING")
        print(f"[REASON] Corrupt raw JSON file: {e}")
        print("[RULE] No fake records will be generated.")
        print("=" * 70)
        return {"status": "PENDING", "reason": f"Corrupt raw file: {e}"}

    if not isinstance(raw_payload, dict) or "ac" not in raw_payload:
        print("LIVE DATA STATUS: PENDING")
        print("[REASON] Payload does not contain valid 'ac' records array.")
        print("[RULE] No fake records will be generated.")
        print("=" * 70)
        return {"status": "PENDING", "reason": "Missing 'ac' key"}

    raw_aircraft_list = raw_payload.get("ac", [])
    if not isinstance(raw_aircraft_list, list):
        print("LIVE DATA STATUS: PENDING")
        print("[REASON] 'ac' is not a list.")
        print("=" * 70)
        return {"status": "PENDING", "reason": "'ac' is not a list"}

    # Read acquisition metadata if present
    acquisition_meta = {}
    if os.path.exists(meta_file_path):
        try:
            with open(meta_file_path, "r", encoding="utf-8") as f:
                acquisition_meta = json.load(f)
        except Exception:
            pass

    utc_cleaning_now = datetime.now(timezone.utc).isoformat()
    if "utc_acquisition_timestamp" in acquisition_meta:
        raw_acquisition_timestamp = acquisition_meta["utc_acquisition_timestamp"]
    else:
        now_val = raw_payload.get("now")
        if now_val:
            try:
                epoch_sec = (float(now_val) / 1000.0) if float(now_val) > 1e11 else float(now_val)
                raw_acquisition_timestamp = datetime.fromtimestamp(epoch_sec, tz=timezone.utc).isoformat()
            except Exception:
                raw_acquisition_timestamp = utc_cleaning_now
        else:
            raw_acquisition_timestamp = utc_cleaning_now

    source_url = acquisition_meta.get(
        "source_url",
        "https://api.adsb.lol/v2/lat/19.0760/lon/72.8777/dist/100"
    )

    cleaned_records = []
    quarantined_records = []

    # Track duplicate hexes
    seen_hexes = set()
    duplicate_hex_count = 0

    for idx, raw_rec in enumerate(raw_aircraft_list):
        if not isinstance(raw_rec, dict):
            quarantined_records.append({
                "record_index": idx,
                "raw_record": raw_rec,
                "quarantine_reasons": ["RECORD_NOT_A_JSON_OBJECT"],
                "quarantined_at_utc": utc_cleaning_now
            })
            continue

        violations = []

        # 1. Identifier Validation & Normalization
        raw_hex = raw_rec.get("hex")
        if not raw_hex or not isinstance(raw_hex, str) or not raw_hex.strip():
            violations.append("MISSING_AIRCRAFT_HEX_IDENTIFIER")
            norm_hex = None
        elif not is_valid_hex_id(raw_hex):
            violations.append(f"INVALID_HEX_IDENTIFIER_FORMAT: '{raw_hex}'")
            norm_hex = raw_hex.strip().upper()
        else:
            norm_hex = raw_hex.strip().upper()
            if norm_hex in seen_hexes:
                duplicate_hex_count += 1
            seen_hexes.add(norm_hex)

        # 2. Coordinate Validation & Normalization
        raw_lat = raw_rec.get("lat")
        raw_lon = raw_rec.get("lon")
        norm_lat = None
        norm_lon = None

        if raw_lat is None or raw_lon is None:
            violations.append("MISSING_GEOSPATIAL_COORDINATES")
        else:
            try:
                lat_float = float(raw_lat)
                if -90.0 <= lat_float <= 90.0:
                    norm_lat = round(lat_float, 6)
                else:
                    violations.append(f"LATITUDE_OUT_OF_BOUNDS: {lat_float} not in [-90, 90]")
            except (ValueError, TypeError):
                violations.append(f"NON_NUMERIC_LATITUDE: '{raw_lat}'")

            try:
                lon_float = float(raw_lon)
                if -180.0 <= lon_float <= 180.0:
                    norm_lon = round(lon_float, 6)
                else:
                    violations.append(f"LONGITUDE_OUT_OF_BOUNDS: {lon_float} not in [-180, 180]")
            except (ValueError, TypeError):
                violations.append(f"NON_NUMERIC_LONGITUDE: '{raw_lon}'")

        # 3. Text Normalization
        raw_flight = raw_rec.get("flight")
        norm_callsign = str(raw_flight).strip().upper() if raw_flight and str(raw_flight).strip() else None

        raw_r = raw_rec.get("r")
        norm_reg = str(raw_r).strip().upper() if raw_r and str(raw_r).strip() else None

        raw_t = raw_rec.get("t")
        norm_type = str(raw_t).strip().upper() if raw_t and str(raw_t).strip() else None

        raw_squawk = raw_rec.get("squawk")
        norm_squawk = str(raw_squawk).strip() if raw_squawk and str(raw_squawk).strip() else None
        if norm_squawk and not re.fullmatch(r"^[0-7]{4}$", norm_squawk):
            # Non-standard squawk (does not necessarily quarantine, but logged)
            pass

        raw_category = raw_rec.get("category")
        norm_category = str(raw_category).strip().upper() if raw_category and str(raw_category).strip() else None

        # 4. Altitude Normalization & Validation
        raw_alt_baro = raw_rec.get("alt_baro")
        norm_alt_baro = None
        is_on_ground = False

        if raw_alt_baro is not None:
            if isinstance(raw_alt_baro, str) and raw_alt_baro.strip().lower() == "ground":
                is_on_ground = True
                norm_alt_baro = 0
            else:
                try:
                    alt_val = float(raw_alt_baro)
                    if -2000 <= alt_val <= 85000:
                        norm_alt_baro = round(alt_val)
                    else:
                        violations.append(f"UNREALISTIC_BAROMETRIC_ALTITUDE: {alt_val} ft")
                except (ValueError, TypeError):
                    violations.append(f"NON_NUMERIC_BARO_ALTITUDE: '{raw_alt_baro}'")

        raw_alt_geom = raw_rec.get("alt_geom")
        norm_alt_geom = None
        if raw_alt_geom is not None:
            try:
                geom_val = float(raw_alt_geom)
                if -2000 <= geom_val <= 85000:
                    norm_alt_geom = round(geom_val)
                else:
                    violations.append(f"UNREALISTIC_GEOMETRIC_ALTITUDE: {geom_val} ft")
            except (ValueError, TypeError):
                pass

        # 5. Speed Normalization & Validation
        raw_gs = raw_rec.get("gs")
        norm_gs = None
        if raw_gs is not None:
            try:
                gs_val = float(raw_gs)
                if 0.0 <= gs_val <= 1500.0:
                    norm_gs = round(gs_val, 1)
                else:
                    violations.append(f"UNREALISTIC_GROUND_SPEED: {gs_val} kts")
            except (ValueError, TypeError):
                violations.append(f"NON_NUMERIC_GROUND_SPEED: '{raw_gs}'")

        # 6. Heading Normalization & Validation
        raw_track = raw_rec.get("track")
        norm_track = None
        if raw_track is not None:
            try:
                track_val = float(raw_track)
                if 0.0 <= track_val <= 360.0:
                    norm_track = round(track_val, 2)
                else:
                    violations.append(f"HEADING_OUT_OF_RANGE: {track_val} deg")
            except (ValueError, TypeError):
                violations.append(f"NON_NUMERIC_HEADING: '{raw_track}'")

        # 7. Vertical Rate Normalization
        raw_baro_rate = raw_rec.get("baro_rate")
        norm_baro_rate = None
        if raw_baro_rate is not None:
            try:
                rate_val = float(raw_baro_rate)
                if -15000 <= rate_val <= 15000:
                    norm_baro_rate = round(rate_val)
            except (ValueError, TypeError):
                pass

        # 8. Sensor Age and Relative Distance Normalization
        def safe_float(v, decimals=2):
            if v is not None:
                try:
                    return round(float(v), decimals)
                except (ValueError, TypeError):
                    return None
            return None

        norm_seen = safe_float(raw_rec.get("seen"), 2)
        norm_seen_pos = safe_float(raw_rec.get("seen_pos"), 2)
        norm_dst = safe_float(raw_rec.get("dst"), 2)
        norm_dir = safe_float(raw_rec.get("dir"), 2)
        norm_rssi = safe_float(raw_rec.get("rssi"), 1)

        # Decision: Quarantine or Cleaned
        if violations:
            quarantined_records.append({
                "record_index": idx,
                "raw_record": raw_rec,
                "quarantine_reasons": violations,
                "quarantined_at_utc": utc_cleaning_now
            })
        else:
            cleaned_record = {
                "aircraft_hex_id": norm_hex,
                "callsign": norm_callsign,
                "registration": norm_reg,
                "aircraft_type_icao": norm_type,
                "squawk_code": norm_squawk,
                "emitter_category": norm_category,
                "latitude": norm_lat,
                "longitude": norm_lon,
                "altitude_baro_ft": norm_alt_baro,
                "altitude_geom_ft": norm_alt_geom,
                "is_on_ground": is_on_ground,
                "ground_speed_kts": norm_gs,
                "true_track_deg": norm_track,
                "vertical_rate_fpm": norm_baro_rate,
                "position_age_seconds": norm_seen_pos,
                "last_seen_seconds": norm_seen,
                "distance_from_center_nm": norm_dst,
                "bearing_from_center_deg": norm_dir,
                "signal_rssi_db": norm_rssi,
                "provenance": {
                    "source_system": "adsb.lol",
                    "source_url": source_url,
                    "query_center_lat": 19.0760,
                    "query_center_lon": 72.8777,
                    "query_radius_nm": 100,
                    "raw_acquisition_utc": raw_acquisition_timestamp,
                    "cleaning_pipeline_utc": utc_cleaning_now,
                    "pipeline_stage": "CLEANED_AND_NORMALIZED",
                    "schema_version": "1.0.0"
                }
            }
            cleaned_records.append(cleaned_record)

    total_raw = len(raw_aircraft_list)
    total_cleaned = len(cleaned_records)
    total_quarantined = len(quarantined_records)

    # Prepare Cleaned Payload
    cleaned_payload = {
        "dataset_metadata": {
            "dataset_id": "BHIV-GEO-QUEST-01-AIRCRAFT",
            "name": "BHIV vNEXT Normalized Aircraft Observation Dataset",
            "source": "adsb.lol / God's Eye View network",
            "source_url": source_url,
            "raw_acquisition_timestamp_utc": raw_acquisition_timestamp,
            "cleaned_timestamp_utc": utc_cleaning_now,
            "total_raw_records": total_raw,
            "total_cleaned_records": total_cleaned,
            "total_quarantined_records": total_quarantined,
            "duplicate_hex_instances": duplicate_hex_count,
            "schema_version": "1.0.0",
            "geographic_center": {"lat": 19.0760, "lon": 72.8777, "radius_nm": 100}
        },
        "records": cleaned_records
    }

    # Prepare Quarantine Payload
    quarantine_payload = {
        "quarantine_metadata": {
            "dataset_id": "BHIV-GEO-QUEST-01-AIRCRAFT-QUARANTINE",
            "source_url": source_url,
            "evaluation_timestamp_utc": utc_cleaning_now,
            "total_quarantined_records": total_quarantined,
            "quarantine_reasons_summary": dict(Counter([r for q in quarantined_records for r in q["quarantine_reasons"]]))
        },
        "quarantined_records": quarantined_records
    }

    # Write files
    os.makedirs(os.path.dirname(cleaned_output_path), exist_ok=True)
    with open(cleaned_output_path, "w", encoding="utf-8") as f:
        json.dump(cleaned_payload, f, indent=2, ensure_ascii=False)

    os.makedirs(os.path.dirname(quarantine_output_path), exist_ok=True)
    with open(quarantine_output_path, "w", encoding="utf-8") as f:
        json.dump(quarantine_payload, f, indent=2, ensure_ascii=False)

    print(f"Total Raw Records Processed:   {total_raw}")
    print(f"Cleaned & Normalized Records:  {total_cleaned}")
    print(f"Quarantined Records:           {total_quarantined}")
    print(f"[SUCCESS] Cleaned records saved to:     {cleaned_output_path}")
    print(f"[SUCCESS] Quarantine records saved to:  {quarantine_output_path}")
    print("=" * 70)

    return {
        "status": "SUCCESS",
        "total_raw": total_raw,
        "total_cleaned": total_cleaned,
        "total_quarantined": total_quarantined
    }

def main():
    parser = argparse.ArgumentParser(description="Clean and normalize ADS-B aircraft dataset")
    parser.add_argument("--raw-file", type=str, default=None, help="Path to raw/aircraft_raw.json")
    parser.add_argument("--meta-file", type=str, default=None, help="Path to raw/acquisition_metadata.json")
    parser.add_argument("--cleaned-file", type=str, default=None, help="Output path for cleaned JSON")
    parser.add_argument("--quarantine-file", type=str, default=None, help="Output path for quarantine JSON")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, ".."))
    
    raw_path = args.raw_file or os.path.join(project_root, "raw", "aircraft_raw.json")
    meta_path = args.meta_file or os.path.join(project_root, "raw", "acquisition_metadata.json")
    cleaned_path = args.cleaned_file or os.path.join(project_root, "cleaned", "aircraft_cleaned.json")
    quarantine_path = args.quarantine_file or os.path.join(project_root, "cleaned", "aircraft_quarantine.json")

    clean_and_normalize_dataset(raw_path, meta_path, cleaned_path, quarantine_path)

if __name__ == "__main__":
    main()
