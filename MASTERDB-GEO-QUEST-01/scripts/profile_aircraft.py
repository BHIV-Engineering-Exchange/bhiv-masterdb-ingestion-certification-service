#!/usr/bin/env python3
"""
BHIV vNEXT MASTERDB-GEO-QUEST-01: Dataset Profiling Script
Operates ONLY on an existing real raw data file (raw/aircraft_raw.json).

CRITICAL DATA INTEGRITY RULE:
If raw/aircraft_raw.json does not exist or contains no real API response:
    Report: LIVE DATA STATUS: PENDING
    Do not generate numbers.
"""

import sys
import os
import json
import argparse
from datetime import datetime, timezone
from collections import Counter, defaultdict
import math

def profile_raw_dataset(raw_file_path: str, output_profile_path: str = None) -> dict:
    """
    Profile the raw aircraft dataset according to strict data integrity rules.
    """
    print("=" * 70)
    print("BHIV vNEXT MASTERDB-GEO-QUEST-01: DATASET PROFILING")
    print("=" * 70)
    print(f"Target Raw File: {raw_file_path}")
    print("-" * 70)

    # Rule: Check if file exists and has content
    if not os.path.exists(raw_file_path) or os.path.getsize(raw_file_path) == 0:
        print("LIVE DATA STATUS: PENDING")
        print(f"[REASON] Raw data file '{raw_file_path}' does not exist or is empty.")
        print("[RULE] No simulated or placeholder statistics will be generated.")
        print("=" * 70)
        return {"live_data_status": "PENDING", "reason": "Raw data file does not exist or is empty"}

    try:
        with open(raw_file_path, "r", encoding="utf-8") as f:
            raw_payload = json.load(f)
    except Exception as e:
        print("LIVE DATA STATUS: PENDING")
        print(f"[REASON] Failed to parse raw JSON: {e}")
        print("[RULE] No simulated or placeholder statistics will be generated.")
        print("=" * 70)
        return {"live_data_status": "PENDING", "reason": f"Corrupt raw file: {e}"}

    # Verify that this is an authentic adsb.lol response structure
    if not isinstance(raw_payload, dict) or "ac" not in raw_payload:
        print("LIVE DATA STATUS: PENDING")
        print("[REASON] File does not contain expected adsb.lol payload structure (missing 'ac' key).")
        print("[RULE] No numbers will be generated for unverified schemas.")
        print("=" * 70)
        return {"live_data_status": "PENDING", "reason": "Missing 'ac' key in payload"}

    aircraft_records = raw_payload.get("ac")
    if not isinstance(aircraft_records, list):
        print("LIVE DATA STATUS: PENDING")
        print("[REASON] 'ac' field is not a list.")
        print("=" * 70)
        return {"live_data_status": "PENDING", "reason": "'ac' field is not a list"}

    total_records = len(aircraft_records)
    api_now = raw_payload.get("now")
    api_msg = raw_payload.get("msg")
    api_total = raw_payload.get("total")
    api_ctime = raw_payload.get("ctime")
    api_ptime = raw_payload.get("ptime")

    if total_records == 0:
        print("LIVE DATA STATUS: ACTIVE (ZERO AIRCRAFT IN AIRSPACE AT QUERY TIME)")
        print(f"API Message: {api_msg}, Server Epoch: {api_now}")
        print("=" * 70)
        return {
            "live_data_status": "ACTIVE_EMPTY",
            "total_aircraft_records": 0,
            "api_msg": api_msg,
            "api_now": api_now
        }

    # 1. Field discovery and data types
    field_occurrences = Counter()
    field_types = defaultdict(set)
    field_null_counts = Counter()

    # Identifiers
    hex_ids = []
    flight_callsigns = []
    registrations = []

    # Coordinates
    lat_values = []
    lon_values = []
    invalid_coords = []
    missing_coords_count = 0

    # Altitudes
    alt_baro_numeric = []
    alt_baro_ground_count = 0
    alt_baro_null_count = 0
    alt_geom_numeric = []

    # Speeds
    speeds_numeric = []
    speeds_null_count = 0

    # Headings
    headings_numeric = []
    headings_null_count = 0

    # Age / Timestamps
    seen_values = []
    seen_pos_values = []

    # Anomalies / Unusual
    emergency_squawks = []
    emergency_flags = []
    categories = Counter()

    for idx, ac in enumerate(aircraft_records):
        if not isinstance(ac, dict):
            continue

        for k, v in ac.items():
            field_occurrences[k] += 1
            type_name = type(v).__name__
            field_types[k].add(type_name)
            if v is None:
                field_null_counts[k] += 1

        # Hex Identifier
        hex_val = ac.get("hex")
        if hex_val:
            hex_ids.append(str(hex_val).lower().strip())
        flight_val = ac.get("flight")
        if flight_val:
            flight_callsigns.append(str(flight_val).strip())
        reg_val = ac.get("r")
        if reg_val:
            registrations.append(str(reg_val).strip())

        # Coordinates
        lat = ac.get("lat")
        lon = ac.get("lon")
        if lat is None or lon is None:
            missing_coords_count += 1
        else:
            is_valid_coord = True
            try:
                lat_f = float(lat)
                lon_f = float(lon)
                if -90.0 <= lat_f <= 90.0:
                    lat_values.append(lat_f)
                else:
                    is_valid_coord = False
                if -180.0 <= lon_f <= 180.0:
                    lon_values.append(lon_f)
                else:
                    is_valid_coord = False
            except (ValueError, TypeError):
                is_valid_coord = False

            if not is_valid_coord:
                invalid_coords.append((idx, hex_val, lat, lon))

        # Altitudes
        alt_b = ac.get("alt_baro")
        if alt_b is None:
            alt_baro_null_count += 1
        elif isinstance(alt_b, str) and alt_b.lower() == "ground":
            alt_baro_ground_count += 1
        else:
            try:
                alt_baro_numeric.append(float(alt_b))
            except (ValueError, TypeError):
                alt_baro_null_count += 1

        alt_g = ac.get("alt_geom")
        if alt_g is not None:
            try:
                alt_geom_numeric.append(float(alt_g))
            except (ValueError, TypeError):
                pass

        # Speed (gs)
        gs = ac.get("gs")
        if gs is not None:
            try:
                speeds_numeric.append(float(gs))
            except (ValueError, TypeError):
                speeds_null_count += 1
        else:
            speeds_null_count += 1

        # Heading (track)
        track = ac.get("track")
        if track is not None:
            try:
                headings_numeric.append(float(track))
            except (ValueError, TypeError):
                headings_null_count += 1
        else:
            headings_null_count += 1

        # Timestamps / Ages
        seen = ac.get("seen")
        if seen is not None:
            try:
                seen_values.append(float(seen))
            except (ValueError, TypeError):
                pass
        seen_pos = ac.get("seen_pos")
        if seen_pos is not None:
            try:
                seen_pos_values.append(float(seen_pos))
            except (ValueError, TypeError):
                pass

        # Squawk & Emergency checks
        squawk = ac.get("squawk")
        if squawk in ("7500", "7600", "7700"):
            emergency_squawks.append((hex_val, squawk))
        emerg = ac.get("emergency")
        if emerg and emerg != "none":
            emergency_flags.append((hex_val, emerg))

        cat = ac.get("category")
        if cat:
            categories[str(cat)] += 1

    # Statistical summaries
    all_fields = sorted(list(field_occurrences.keys()))
    unique_hex_count = len(set(hex_ids))
    duplicate_hex_count = len(hex_ids) - unique_hex_count
    duplicate_hexes = [item for item, count in Counter(hex_ids).items() if count > 1]

    def stats_summary(arr):
        if not arr:
            return {"count": 0, "min": None, "max": None, "mean": None}
        return {
            "count": len(arr),
            "min": round(min(arr), 4),
            "max": round(max(arr), 4),
            "mean": round(sum(arr) / len(arr), 4)
        }

    profiling_result = {
        "profiling_utc": datetime.now(timezone.utc).isoformat(),
        "live_data_status": "PROFILED",
        "raw_source_file": raw_file_path,
        "api_metadata": {
            "now_epoch": api_now,
            "msg": api_msg,
            "total_reported_by_api": api_total,
            "ptime": api_ptime,
            "ctime": api_ctime
        },
        "records": {
            "total_aircraft_records": total_records,
            "unique_hex_identifiers": unique_hex_count,
            "duplicate_hex_count": duplicate_hex_count,
            "duplicate_hex_list": duplicate_hexes,
            "with_callsign_count": len(flight_callsigns),
            "with_registration_count": len(registrations)
        },
        "fields": {
            "total_unique_fields": len(all_fields),
            "field_list": all_fields,
            "field_details": {
                f: {
                    "present_records": field_occurrences[f],
                    "coverage_percentage": round((field_occurrences[f] / total_records) * 100, 2),
                    "missing_or_absent_count": total_records - field_occurrences[f] + field_null_counts[f],
                    "data_types": sorted(list(field_types[f]))
                }
                for f in all_fields
            }
        },
        "coordinates": {
            "records_with_coordinates": total_records - missing_coords_count,
            "records_missing_coordinates": missing_coords_count,
            "records_with_invalid_coordinates": len(invalid_coords),
            "invalid_coordinate_details": invalid_coords,
            "latitude_stats": stats_summary(lat_values),
            "longitude_stats": stats_summary(lon_values),
            "lat_in_wgs84_bounds": len(invalid_coords) == 0 and len(lat_values) > 0,
            "lon_in_wgs84_bounds": len(invalid_coords) == 0 and len(lon_values) > 0
        },
        "altitudes": {
            "alt_baro_numeric_stats": stats_summary(alt_baro_numeric),
            "on_ground_count": alt_baro_ground_count,
            "alt_baro_null_count": alt_baro_null_count,
            "alt_geom_numeric_stats": stats_summary(alt_geom_numeric)
        },
        "speeds_ground_knots": {
            "speed_stats": stats_summary(speeds_numeric),
            "speed_null_count": speeds_null_count
        },
        "headings_true_degrees": {
            "heading_stats": stats_summary(headings_numeric),
            "heading_null_count": headings_null_count,
            "all_within_0_360": all(0.0 <= h <= 360.0 for h in headings_numeric) if headings_numeric else True
        },
        "timestamps_and_age": {
            "seen_seconds_stats": stats_summary(seen_values),
            "seen_pos_seconds_stats": stats_summary(seen_pos_values)
        },
        "unusual_and_flags": {
            "emergency_squawks": emergency_squawks,
            "emergency_flags": emergency_flags,
            "emitter_categories": dict(categories)
        }
    }

    # Print summary to stdout
    print(f"Total Aircraft Records:        {total_records}")
    print(f"Unique Aircraft Hex Identifiers: {unique_hex_count}")
    print(f"Duplicate Aircraft Hex IDs:    {duplicate_hex_count}")
    print(f"Total Unique Fields Present:   {len(all_fields)}")
    print(f"Records with Coordinates:      {total_records - missing_coords_count}/{total_records} ({(total_records - missing_coords_count)/total_records*100:.1f}%)")
    print(f"Latitude Range:                {profiling_result['coordinates']['latitude_stats']['min']} to {profiling_result['coordinates']['latitude_stats']['max']} deg")
    print(f"Longitude Range:               {profiling_result['coordinates']['longitude_stats']['min']} to {profiling_result['coordinates']['longitude_stats']['max']} deg")
    print(f"Barometric Altitude Range:     {profiling_result['altitudes']['alt_baro_numeric_stats']['min']} to {profiling_result['altitudes']['alt_baro_numeric_stats']['max']} ft (Ground: {alt_baro_ground_count})")
    print(f"Ground Speed Range:            {profiling_result['speeds_ground_knots']['speed_stats']['min']} to {profiling_result['speeds_ground_knots']['speed_stats']['max']} kts")
    print(f"True Heading Range:            {profiling_result['headings_true_degrees']['heading_stats']['min']} to {profiling_result['headings_true_degrees']['heading_stats']['max']} deg")
    print(f"Emergency Squawks/Flags:       {len(emergency_squawks)} squawks, {len(emergency_flags)} flags")
    print("-" * 70)

    # Save to profiling report file if specified or default
    if output_profile_path:
        os.makedirs(os.path.dirname(output_profile_path), exist_ok=True)
        with open(output_profile_path, "w", encoding="utf-8") as f:
            json.dump(profiling_result, f, indent=2)
        print(f"[SUCCESS] Saved profiling metrics to: {output_profile_path}")

    print("=" * 70)
    return profiling_result

def main():
    parser = argparse.ArgumentParser(description="Profile real raw ADS-B aircraft dataset")
    parser.add_argument("--raw-file", type=str, default=None, help="Path to raw/aircraft_raw.json")
    parser.add_argument("--output-profile", type=str, default=None, help="Path to output validation/profiling_report.json")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, ".."))
    
    raw_path = args.raw_file or os.path.join(project_root, "raw", "aircraft_raw.json")
    output_profile = args.output_profile or os.path.join(project_root, "validation", "profiling_report.json")

    profile_raw_dataset(raw_path, output_profile)

if __name__ == "__main__":
    main()
