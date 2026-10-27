#!/usr/bin/env python3
"""
BHIV vNEXT MASTERDB-GEO-QUEST-01: Data Quality Validation Script
Validates cleaned aircraft dataset against strict quality gates and produces
validation/aircraft_quality_report.json.

CRITICAL DATA INTEGRITY RULE:
If live data was not obtained, clearly state:
"Live data validation: PENDING — source API was not successfully accessed."
Do not invent counts or PASS results.
"""

import sys
import os
import json
import argparse
from datetime import datetime, timezone

SCRIPT_VERSION = "1.0.0"

def validate_aircraft_data(
    raw_file_path: str,
    cleaned_file_path: str,
    quarantine_file_path: str,
    output_report_path: str
) -> dict:
    """
    Execute comprehensive quality gates on raw, cleaned, and quarantine datasets.
    """
    utc_execution = datetime.now(timezone.utc).isoformat()

    print("=" * 70)
    print("BHIV vNEXT MASTERDB-GEO-QUEST-01: QUALITY VALIDATION")
    print("=" * 70)
    print(f"Cleaned Data File:    {cleaned_file_path}")
    print(f"Quarantine File:      {quarantine_file_path}")
    print(f"Output Report Path:   {output_report_path}")
    print(f"Execution UTC:        {utc_execution}")
    print("-" * 70)

    # Gate 1: Check existence of data files
    if not os.path.exists(cleaned_file_path) or not os.path.exists(raw_file_path):
        print("Live data validation: PENDING -- source API was not successfully accessed.")
        pending_report = {
            "live_data_validation": "PENDING -- source API was not successfully accessed.",
            "execution_utc": utc_execution,
            "script_version": SCRIPT_VERSION,
            "raw_dataset_found": os.path.exists(raw_file_path),
            "cleaned_dataset_found": os.path.exists(cleaned_file_path),
            "message": "Validation cannot execute on uncollected or missing data. Zero counts or artificial passes will NOT be produced."
        }
        os.makedirs(os.path.dirname(output_report_path), exist_ok=True)
        with open(output_report_path, "w", encoding="utf-8") as f:
            json.dump(pending_report, f, indent=2)
        print("=" * 70)
        return pending_report

    try:
        with open(raw_file_path, "r", encoding="utf-8") as f:
            raw_payload = json.load(f)
        with open(cleaned_file_path, "r", encoding="utf-8") as f:
            cleaned_payload = json.load(f)
        with open(quarantine_file_path, "r", encoding="utf-8") as f:
            quarantine_payload = json.load(f)
    except Exception as e:
        error_report = {
            "live_data_validation": f"FAILED — error reading dataset files: {e}",
            "execution_utc": utc_execution,
            "script_version": SCRIPT_VERSION
        }
        os.makedirs(os.path.dirname(output_report_path), exist_ok=True)
        with open(output_report_path, "w", encoding="utf-8") as f:
            json.dump(error_report, f, indent=2)
        return error_report

    raw_records = raw_payload.get("ac", [])
    cleaned_records = cleaned_payload.get("records", [])
    quarantined_records = quarantine_payload.get("quarantined_records", [])

    raw_count = len(raw_records)
    cleaned_count = len(cleaned_records)
    quarantined_count = len(quarantined_records)

    checks = []

    # Check 1: Record Accounting / Conservation
    check_1_pass = (raw_count == cleaned_count + quarantined_count)
    checks.append({
        "check_id": "CHK_01_RECORD_CONSERVATION",
        "name": "Raw record count equals cleaned plus quarantined count",
        "status": "PASS" if check_1_pass else "FAIL",
        "details": {
            "raw_count": raw_count,
            "cleaned_count": cleaned_count,
            "quarantined_count": quarantined_count,
            "sum_cleaned_quarantine": cleaned_count + quarantined_count
        }
    })

    # Check 2: Unique Aircraft Identifiers in Cleaned Set
    hex_list = [r.get("aircraft_hex_id") for r in cleaned_records if r.get("aircraft_hex_id")]
    unique_hex_count = len(set(hex_list))
    duplicate_hex_count = len(hex_list) - unique_hex_count
    check_2_pass = (duplicate_hex_count == 0)
    checks.append({
        "check_id": "CHK_02_IDENTIFIER_UNIQUENESS",
        "name": "Zero duplicate aircraft hex identifiers in cleaned set",
        "status": "PASS" if check_2_pass else "FAIL",
        "details": {
            "total_cleaned_identifiers": len(hex_list),
            "unique_identifiers": unique_hex_count,
            "duplicate_count": duplicate_hex_count
        }
    })

    # Check 3: Mandatory Geographic Coordinates Valid & Present
    missing_coords = 0
    invalid_lats = 0
    invalid_lons = 0
    for r in cleaned_records:
        lat = r.get("latitude")
        lon = r.get("longitude")
        if lat is None or lon is None:
            missing_coords += 1
        else:
            if not (-90.0 <= lat <= 90.0):
                invalid_lats += 1
            if not (-180.0 <= lon <= 180.0):
                invalid_lons += 1

    check_3_pass = (missing_coords == 0 and invalid_lats == 0 and invalid_lons == 0)
    checks.append({
        "check_id": "CHK_03_COORDINATE_VALIDITY",
        "name": "All cleaned records possess valid WGS84 latitude and longitude coordinates",
        "status": "PASS" if check_3_pass else "FAIL",
        "details": {
            "records_evaluated": cleaned_count,
            "missing_coordinates": missing_coords,
            "invalid_latitudes": invalid_lats,
            "invalid_longitudes": invalid_lons
        }
    })

    # Check 4: Numeric Range Validity (Speed, Track, Altitude)
    invalid_speeds = 0
    invalid_tracks = 0
    invalid_altitudes = 0
    for r in cleaned_records:
        gs = r.get("ground_speed_kts")
        if gs is not None and not (0.0 <= gs <= 1500.0):
            invalid_speeds += 1
        
        track = r.get("true_track_deg")
        if track is not None and not (0.0 <= track <= 360.0):
            invalid_tracks += 1
            
        alt = r.get("altitude_baro_ft")
        if alt is not None and not (-2000 <= alt <= 85000):
            invalid_altitudes += 1

    check_4_pass = (invalid_speeds == 0 and invalid_tracks == 0 and invalid_altitudes == 0)
    checks.append({
        "check_id": "CHK_04_NUMERIC_RANGE_VALIDITY",
        "name": "Ground speeds, tracks, and altitudes within physically realistic aviation envelopes",
        "status": "PASS" if check_4_pass else "FAIL",
        "details": {
            "invalid_speed_count": invalid_speeds,
            "invalid_track_count": invalid_tracks,
            "invalid_altitude_count": invalid_altitudes
        }
    })

    # Check 5: Timestamp & Age Field Integrity
    invalid_ages = 0
    for r in cleaned_records:
        seen = r.get("last_seen_seconds")
        if seen is not None and seen < 0:
            invalid_ages += 1
        seen_pos = r.get("position_age_seconds")
        if seen_pos is not None and seen_pos < 0:
            invalid_ages += 1

    check_5_pass = (invalid_ages == 0)
    checks.append({
        "check_id": "CHK_05_TIMESTAMP_AGE_INTEGRITY",
        "name": "Observation age and sensor latency values are non-negative",
        "status": "PASS" if check_5_pass else "FAIL",
        "details": {
            "invalid_sensor_age_count": invalid_ages
        }
    })

    # Check 6: Provenance Completeness
    missing_provenance = 0
    for r in cleaned_records:
        prov = r.get("provenance")
        if not prov or not isinstance(prov, dict):
            missing_provenance += 1
        elif not prov.get("source_url") or not prov.get("raw_acquisition_utc"):
            missing_provenance += 1

    check_6_pass = (missing_provenance == 0)
    checks.append({
        "check_id": "CHK_06_PROVENANCE_COMPLETENESS",
        "name": "Every cleaned record maintains complete source lineage and audit provenance",
        "status": "PASS" if check_6_pass else "FAIL",
        "details": {
            "missing_provenance_count": missing_provenance
        }
    })

    # Check 7: Field completeness and missing-value statistics
    all_cleaned_fields = [
        "aircraft_hex_id", "callsign", "registration", "aircraft_type_icao",
        "squawk_code", "emitter_category", "latitude", "longitude",
        "altitude_baro_ft", "altitude_geom_ft", "is_on_ground",
        "ground_speed_kts", "true_track_deg", "vertical_rate_fpm",
        "position_age_seconds", "last_seen_seconds", "distance_from_center_nm",
        "bearing_from_center_deg", "signal_rssi_db", "provenance"
    ]

    missing_value_stats = {}
    for fld in all_cleaned_fields:
        missing_count = sum(1 for r in cleaned_records if r.get(fld) is None)
        missing_pct = round((missing_count / cleaned_count * 100), 2) if cleaned_count > 0 else 0.0
        missing_value_stats[fld] = {
            "present_count": cleaned_count - missing_count,
            "missing_count": missing_count,
            "missing_percentage": missing_pct
        }

    overall_pass = all(c["status"] == "PASS" for c in checks)

    quality_report = {
        "execution_utc": utc_execution,
        "script_version": SCRIPT_VERSION,
        "live_data_validation": "EXECUTED_ON_LIVE_DATA",
        "overall_status": "PASS" if overall_pass else "FAIL",
        "record_counts": {
            "raw_record_count": raw_count,
            "cleaned_record_count": cleaned_count,
            "quarantined_record_count": quarantined_count,
            "duplicate_count": duplicate_hex_count
        },
        "coordinate_validation": {
            "status": "PASS" if check_3_pass else "FAIL",
            "lat_bounds": [-90.0, 90.0],
            "lon_bounds": [-180.0, 180.0],
            "records_evaluated": cleaned_count,
            "missing_coordinates": missing_coords
        },
        "numeric_validation": {
            "status": "PASS" if check_4_pass else "FAIL",
            "invalid_speed_count": invalid_speeds,
            "invalid_track_count": invalid_tracks,
            "invalid_altitude_count": invalid_altitudes
        },
        "timestamp_validation": {
            "status": "PASS" if check_5_pass else "FAIL",
            "invalid_age_count": invalid_ages
        },
        "missing_value_statistics": missing_value_stats,
        "executed_checks": checks
    }

    os.makedirs(os.path.dirname(output_report_path), exist_ok=True)
    with open(output_report_path, "w", encoding="utf-8") as f:
        json.dump(quality_report, f, indent=2)

    # Print summary
    print(f"Validation Status:       {quality_report['overall_status']}")
    print(f"Raw Records:             {raw_count}")
    print(f"Cleaned Records:         {cleaned_count}")
    print(f"Quarantined Records:     {quarantined_count}")
    print(f"Duplicate Identifiers:   {duplicate_hex_count}")
    for c in checks:
        print(f"  - [{c['status']}] {c['check_id']}: {c['name']}")
    print(f"[SUCCESS] Quality report saved to: {output_report_path}")
    print("=" * 70)

    return quality_report

def main():
    parser = argparse.ArgumentParser(description="Validate cleaned ADS-B aircraft dataset")
    parser.add_argument("--raw-file", type=str, default=None, help="Path to raw/aircraft_raw.json")
    parser.add_argument("--cleaned-file", type=str, default=None, help="Path to cleaned/aircraft_cleaned.json")
    parser.add_argument("--quarantine-file", type=str, default=None, help="Path to cleaned/aircraft_quarantine.json")
    parser.add_argument("--output-report", type=str, default=None, help="Path to validation/aircraft_quality_report.json")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, ".."))
    
    raw_path = args.raw_file or os.path.join(project_root, "raw", "aircraft_raw.json")
    cleaned_path = args.cleaned_file or os.path.join(project_root, "cleaned", "aircraft_cleaned.json")
    quarantine_path = args.quarantine_file or os.path.join(project_root, "cleaned", "aircraft_quarantine.json")
    output_report = args.output_report or os.path.join(project_root, "validation", "aircraft_quality_report.json")

    validate_aircraft_data(raw_path, cleaned_path, quarantine_path, output_report)

if __name__ == "__main__":
    main()
