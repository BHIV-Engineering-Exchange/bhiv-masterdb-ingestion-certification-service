#!/usr/bin/env python3
"""
BHIV vNEXT MASTERDB-GEO-QUEST-01: Deterministic Quality Rule Evaluator
Evaluates datasets against the 10 rules in the Rule Catalogue, classifies warnings vs hard failures,
routes invalid records to quarantine, and maintains an immutable Exception Register without silent data loss.
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

HEX_REGEX = re.compile(r"^[0-9A-Fa-f]{1,6}$")
SQUAWK_REGEX = re.compile(r"^[0-7]{4}$")

MANDATORY_FIELDS = ["aircraft_hex_id", "latitude", "longitude", "is_on_ground", "provenance"]

def evaluate_record(
    record: Dict[str, Any],
    record_index: int,
    seen_hexes: set,
    raw_acquisition_timestamp: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Evaluate a single aircraft record against rules RULE-GEO-002 through RULE-GEO-008.
    Returns (hard_failures, warnings).
    """
    hard_failures = []
    warnings = []

    if not isinstance(record, dict):
        hard_failures.append({
            "rule_id": "RULE-GEO-007",
            "field": "record",
            "actual_value": str(type(record)),
            "expected_condition": "Record must be a JSON object",
            "severity": "HARD_FAILURE",
            "disposition": "QUARANTINED",
            "message": "Encountered non-dict record in surveillance collection"
        })
        return hard_failures, warnings

    hex_id = record.get("aircraft_hex_id") or record.get("hex")

    # RULE-GEO-007: Mandatory Schema Conformance
    for mf in MANDATORY_FIELDS:
        val = record.get(mf)
        if mf == "aircraft_hex_id":
            val = hex_id
        if val is None:
            hard_failures.append({
                "rule_id": "RULE-GEO-007",
                "field": mf,
                "actual_value": None,
                "expected_condition": f"Field '{mf}' is mandatory and non-nullable",
                "severity": "HARD_FAILURE",
                "disposition": "QUARANTINED",
                "message": f"Mandatory schema attribute '{mf}' is missing or null"
            })

    # RULE-GEO-002: Identifier Uniqueness & Format
    if hex_id is not None:
        if not isinstance(hex_id, str) or not HEX_REGEX.fullmatch(hex_id.strip()):
            hard_failures.append({
                "rule_id": "RULE-GEO-002",
                "field": "aircraft_hex_id",
                "actual_value": str(hex_id),
                "expected_condition": "Valid 24-bit hexadecimal Mode S transponder address (1-6 hex characters)",
                "severity": "HARD_FAILURE",
                "disposition": "QUARANTINED",
                "message": f"Invalid Mode S hex address format: '{hex_id}'"
            })
        else:
            norm_hex = hex_id.strip().upper()
            if norm_hex in seen_hexes:
                hard_failures.append({
                    "rule_id": "RULE-GEO-002",
                    "field": "aircraft_hex_id",
                    "actual_value": norm_hex,
                    "expected_condition": "Mode S hex address must be unique within surveillance batch",
                    "severity": "HARD_FAILURE",
                    "disposition": "QUARANTINED",
                    "message": f"Duplicate aircraft hex address detected: '{norm_hex}'"
                })
            seen_hexes.add(norm_hex)

    # RULE-GEO-003: Coordinate Spatial Envelope
    lat = record.get("latitude") if record.get("latitude") is not None else record.get("lat")
    lon = record.get("longitude") if record.get("longitude") is not None else record.get("lon")

    if lat is not None:
        try:
            lat_f = float(lat)
            if not (-90.0 <= lat_f <= 90.0):
                hard_failures.append({
                    "rule_id": "RULE-GEO-003",
                    "field": "latitude",
                    "actual_value": lat_f,
                    "expected_condition": "Latitude must be within WGS84 range [-90.0, +90.0]",
                    "severity": "HARD_FAILURE",
                    "disposition": "QUARANTINED",
                    "message": f"Latitude {lat_f} is outside WGS84 spatial bounds"
                })
        except (ValueError, TypeError):
            hard_failures.append({
                "rule_id": "RULE-GEO-003",
                "field": "latitude",
                "actual_value": str(lat),
                "expected_condition": "Latitude must be a valid float",
                "severity": "HARD_FAILURE",
                "disposition": "QUARANTINED",
                "message": f"Latitude '{lat}' is not a valid numeric float"
            })

    if lon is not None:
        try:
            lon_f = float(lon)
            if not (-180.0 <= lon_f <= 180.0):
                hard_failures.append({
                    "rule_id": "RULE-GEO-003",
                    "field": "longitude",
                    "actual_value": lon_f,
                    "expected_condition": "Longitude must be within WGS84 range [-180.0, +180.0]",
                    "severity": "HARD_FAILURE",
                    "disposition": "QUARANTINED",
                    "message": f"Longitude {lon_f} is outside WGS84 spatial bounds"
                })
        except (ValueError, TypeError):
            hard_failures.append({
                "rule_id": "RULE-GEO-003",
                "field": "longitude",
                "actual_value": str(lon),
                "expected_condition": "Longitude must be a valid float",
                "severity": "HARD_FAILURE",
                "disposition": "QUARANTINED",
                "message": f"Longitude '{lon}' is not a valid numeric float"
            })

    # RULE-GEO-004: Kinematic Aviation Range Envelopes
    gs = record.get("ground_speed_kts") if record.get("ground_speed_kts") is not None else record.get("gs")
    if gs is not None:
        try:
            gs_f = float(gs)
            if not (0.0 <= gs_f <= 1500.0):
                hard_failures.append({
                    "rule_id": "RULE-GEO-004",
                    "field": "ground_speed_kts",
                    "actual_value": gs_f,
                    "expected_condition": "Ground speed must be within [0.0, 1500.0] kts",
                    "severity": "HARD_FAILURE",
                    "disposition": "QUARANTINED",
                    "message": f"Ground speed {gs_f} kts exceeds physical civil/military aviation envelope"
                })
        except (ValueError, TypeError):
            hard_failures.append({
                "rule_id": "RULE-GEO-004",
                "field": "ground_speed_kts",
                "actual_value": str(gs),
                "expected_condition": "Ground speed must be a numeric value",
                "severity": "HARD_FAILURE",
                "disposition": "QUARANTINED",
                "message": f"Ground speed '{gs}' is non-numeric"
            })

    alt_baro = record.get("altitude_baro_ft") if record.get("altitude_baro_ft") is not None else record.get("alt_baro")
    if alt_baro is not None and not (isinstance(alt_baro, str) and alt_baro.lower() == "ground"):
        try:
            if isinstance(alt_baro, list):
                raise TypeError("altitude cannot be a list")
            alt_f = float(alt_baro)
            if not (-2000.0 <= alt_f <= 85000.0):
                hard_failures.append({
                    "rule_id": "RULE-GEO-004",
                    "field": "altitude_baro_ft",
                    "actual_value": alt_f,
                    "expected_condition": "Barometric altitude must be within [-2000, 85000] ft",
                    "severity": "HARD_FAILURE",
                    "disposition": "QUARANTINED",
                    "message": f"Barometric altitude {alt_f} ft is outside realistic physical flight limits"
                })
        except (ValueError, TypeError):
            hard_failures.append({
                "rule_id": "RULE-GEO-004",
                "field": "altitude_baro_ft",
                "actual_value": str(alt_baro),
                "expected_condition": "Barometric altitude must be numeric or 'ground'",
                "severity": "HARD_FAILURE",
                "disposition": "QUARANTINED",
                "message": f"Barometric altitude '{alt_baro}' is malformed or non-numeric"
            })

    track = record.get("true_track_deg") if record.get("true_track_deg") is not None else record.get("track")
    if track is not None:
        try:
            track_f = float(track)
            if not (0.0 <= track_f <= 360.0):
                hard_failures.append({
                    "rule_id": "RULE-GEO-004",
                    "field": "true_track_deg",
                    "actual_value": track_f,
                    "expected_condition": "True track course must be within [0.0, 360.0] deg",
                    "severity": "HARD_FAILURE",
                    "disposition": "QUARANTINED",
                    "message": f"True track heading {track_f} deg is out of bounds"
                })
        except (ValueError, TypeError):
            hard_failures.append({
                "rule_id": "RULE-GEO-004",
                "field": "true_track_deg",
                "actual_value": str(track),
                "expected_condition": "True track heading must be numeric",
                "severity": "HARD_FAILURE",
                "disposition": "QUARANTINED",
                "message": f"True track '{track}' is non-numeric"
            })

    # RULE-GEO-005: Temporal Latency & Freshness
    seen = record.get("last_seen_seconds") if record.get("last_seen_seconds") is not None else record.get("seen")
    seen_pos = record.get("position_age_seconds") if record.get("position_age_seconds") is not None else record.get("seen_pos")

    for lat_name, lat_val in [("last_seen_seconds", seen), ("position_age_seconds", seen_pos)]:
        if lat_val is not None:
            try:
                lat_f = float(lat_val)
                if lat_f < 0.0:
                    hard_failures.append({
                        "rule_id": "RULE-GEO-005",
                        "field": lat_name,
                        "actual_value": lat_f,
                        "expected_condition": f"Sensor latency '{lat_name}' must be non-negative",
                        "severity": "HARD_FAILURE",
                        "disposition": "QUARANTINED",
                        "message": f"Negative sensor latency {lat_f}s indicates clock skew or corrupted timing"
                    })
                elif lat_f > 300.0:
                    warnings.append({
                        "rule_id": "RULE-GEO-005",
                        "field": lat_name,
                        "actual_value": lat_f,
                        "expected_condition": f"Sensor latency '{lat_name}' <= 300.0s for near real-time surveillance",
                        "severity": "WARNING",
                        "disposition": "FLAGGED_STALE",
                        "message": f"Telemetry latency {lat_f}s exceeds 300s freshness threshold; record flagged as STALE"
                    })
            except (ValueError, TypeError):
                pass

    # RULE-GEO-006: Lineage & Provenance Completeness
    prov = record.get("provenance")
    if prov is None or not isinstance(prov, dict):
        hard_failures.append({
            "rule_id": "RULE-GEO-006",
            "field": "provenance",
            "actual_value": str(prov),
            "expected_condition": "Record must contain a valid provenance dictionary",
            "severity": "HARD_FAILURE",
            "disposition": "QUARANTINED",
            "message": "Missing audit provenance block in record"
        })
    else:
        if not prov.get("source_url"):
            hard_failures.append({
                "rule_id": "RULE-GEO-006",
                "field": "provenance.source_url",
                "actual_value": None,
                "expected_condition": "Provenance must declare upstream source_url",
                "severity": "HARD_FAILURE",
                "disposition": "QUARANTINED",
                "message": "Provenance missing source_url"
            })
        if not prov.get("raw_acquisition_utc"):
            hard_failures.append({
                "rule_id": "RULE-GEO-006",
                "field": "provenance.raw_acquisition_utc",
                "actual_value": None,
                "expected_condition": "Provenance must declare raw_acquisition_utc timestamp",
                "severity": "HARD_FAILURE",
                "disposition": "QUARANTINED",
                "message": "Provenance missing raw_acquisition_utc"
            })

    # RULE-GEO-008: Surface State Measurement Decoupling & Consistency
    is_ground = record.get("is_on_ground")
    if is_ground is True:
        # Check altitude consistency
        if alt_baro is not None and not (isinstance(alt_baro, str) and alt_baro.lower() == "ground"):
            try:
                alt_num = float(alt_baro)
                if alt_num > 500:
                    hard_failures.append({
                        "rule_id": "RULE-GEO-008",
                        "field": "altitude_baro_ft",
                        "actual_value": alt_num,
                        "expected_condition": "Surface aircraft (is_on_ground=True) must have altitude <= 500 ft",
                        "severity": "HARD_FAILURE",
                        "disposition": "QUARANTINED",
                        "message": f"Contradictory state: aircraft flagged as on ground but reporting {alt_num} ft altitude"
                    })
            except (ValueError, TypeError):
                pass
        # Check speed consistency on ground
        if gs is not None:
            try:
                gs_num = float(gs)
                if gs_num > 200.0:
                    hard_failures.append({
                        "rule_id": "RULE-GEO-008",
                        "field": "ground_speed_kts",
                        "actual_value": gs_num,
                        "expected_condition": "Surface taxi speed must be <= 200 kts",
                        "severity": "HARD_FAILURE",
                        "disposition": "QUARANTINED",
                        "message": f"Contradictory state: aircraft flagged as on ground but reporting {gs_num} kts speed"
                    })
            except (ValueError, TypeError):
                pass

    return hard_failures, warnings


def evaluate_batch(
    records: List[Dict[str, Any]],
    raw_count: Optional[int] = None,
    dataset_metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Evaluate an entire surveillance batch against all 10 rules.
    Produces structured validation summary and exception records.
    """
    utc_now = datetime.now(timezone.utc).isoformat()
    seen_hexes = set()
    cleaned_records = []
    quarantined_records = []
    exception_records = []

    exc_counter = 1

    for idx, rec in enumerate(records):
        hard_failures, warnings = evaluate_record(rec, idx, seen_hexes)
        rec_id = (rec.get("aircraft_hex_id") or rec.get("hex") or f"INDEX_{idx}") if isinstance(rec, dict) else f"INDEX_{idx}"

        for w in warnings:
            exception_records.append({
                "exception_id": f"EXC-WARN-{exc_counter:04d}",
                "timestamp_utc": utc_now,
                "rule_id": w["rule_id"],
                "record_id": str(rec_id),
                "field": w["field"],
                "actual_value": w["actual_value"],
                "expected_condition": w["expected_condition"],
                "severity": "WARNING",
                "disposition": w["disposition"],
                "message": w["message"]
            })
            exc_counter += 1

        if hard_failures:
            for hf in hard_failures:
                exception_records.append({
                    "exception_id": f"EXC-ERR-{exc_counter:04d}",
                    "timestamp_utc": utc_now,
                    "rule_id": hf["rule_id"],
                    "record_id": str(rec_id),
                    "field": hf["field"],
                    "actual_value": hf["actual_value"],
                    "expected_condition": hf["expected_condition"],
                    "severity": "HARD_FAILURE",
                    "disposition": hf["disposition"],
                    "message": hf["message"]
                })
                exc_counter += 1
            quarantined_records.append({
                "record_index": idx,
                "record_id": str(rec_id),
                "raw_record": rec,
                "quarantine_reasons": [hf["message"] for hf in hard_failures],
                "quarantined_at_utc": utc_now
            })
        else:
            cleaned_records.append(rec)

    # RULE-GEO-001: Record Conservation Check
    expected_raw_count = raw_count if raw_count is not None else len(records)
    actual_sum = len(cleaned_records) + len(quarantined_records)
    conservation_pass = (expected_raw_count == actual_sum)

    if not conservation_pass:
        exception_records.append({
            "exception_id": f"EXC-ERR-{exc_counter:04d}",
            "timestamp_utc": utc_now,
            "rule_id": "RULE-GEO-001",
            "record_id": "BATCH_ACCOUNTING",
            "field": "record_conservation",
            "actual_value": actual_sum,
            "expected_condition": f"Sum of cleaned ({len(cleaned_records)}) + quarantined ({len(quarantined_records)}) must equal raw ({expected_raw_count})",
            "severity": "HARD_FAILURE",
            "disposition": "REJECT_BATCH",
            "message": f"Mathematical conservation failure: raw={expected_raw_count} != sum={actual_sum}"
        })
        exc_counter += 1

    # Metadata Level Checks (RULE-GEO-009 & RULE-GEO-010)
    if dataset_metadata:
        # RULE-GEO-009: Dataset Identity vs Schema Disambiguation
        ds_id = dataset_metadata.get("dataset_id")
        schema_v = dataset_metadata.get("schema_version")
        if ds_id and schema_v and ds_id == schema_v:
            exception_records.append({
                "exception_id": f"EXC-ERR-{exc_counter:04d}",
                "timestamp_utc": utc_now,
                "rule_id": "RULE-GEO-009",
                "record_id": "DATASET_CONTRACT",
                "field": "dataset_id",
                "actual_value": ds_id,
                "expected_condition": "dataset_id must be distinct from schema_version",
                "severity": "HARD_FAILURE",
                "disposition": "REJECT_PAYLOAD",
                "message": "Dataset ID and schema version are ambiguous/identical"
            })
            exc_counter += 1

        # RULE-GEO-010: License Compliance
        licence_str = dataset_metadata.get("licence", "")
        if isinstance(licence_str, dict):
            licence_name = licence_str.get("data_licence_name") or licence_str.get("licence_name", "")
        else:
            licence_name = str(licence_str)
        if "ODbL" not in licence_name and "Open Data Commons" not in licence_name:
            exception_records.append({
                "exception_id": f"EXC-ERR-{exc_counter:04d}",
                "timestamp_utc": utc_now,
                "rule_id": "RULE-GEO-010",
                "record_id": "LEGAL_LICENCE",
                "field": "licence",
                "actual_value": licence_name,
                "expected_condition": "Must declare ODbL v1.0 license",
                "severity": "HARD_FAILURE",
                "disposition": "REJECT_ASSET",
                "message": f"Non-compliant license declaration: '{licence_name}'"
            })
            exc_counter += 1

    hard_failure_count = sum(1 for e in exception_records if e["severity"] == "HARD_FAILURE")
    warning_count = sum(1 for e in exception_records if e["severity"] == "WARNING")

    return {
        "evaluation_timestamp_utc": utc_now,
        "input_record_count": len(records),
        "cleaned_record_count": len(cleaned_records),
        "quarantined_record_count": len(quarantined_records),
        "conservation_verified": conservation_pass,
        "hard_failure_count": hard_failure_count,
        "warning_count": warning_count,
        "overall_status": "PASS" if hard_failure_count == 0 else "FAIL",
        "exceptions": exception_records,
        "cleaned_records": cleaned_records,
        "quarantined_records": quarantined_records
    }

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Evaluate aircraft records against quality rules")
    parser.add_argument("--input", required=True, help="Input JSON file containing records array")
    parser.add_argument("--output-exceptions", required=True, help="Output JSON path for exception register")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)
    records = data.get("records", data.get("ac", []))
    res = evaluate_batch(records)
    os.makedirs(os.path.dirname(args.output_exceptions), exist_ok=True)
    with open(args.output_exceptions, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    print(f"Evaluated {len(records)} records. Status: {res['overall_status']}, Exceptions: {len(res['exceptions'])}")
