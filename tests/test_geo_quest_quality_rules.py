"""
BHIV vNEXT MASTERDB-GEO-QUEST-01: Quality Gate & Deterministic Validation Rule Tests
Executes comprehensive assertions for rules RULE-GEO-001 through RULE-GEO-010,
verifies test fixtures, and validates exception handling.
"""

import json
from pathlib import Path
import sys
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent / "MASTERDB-GEO-QUEST-01"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.rule_evaluator import evaluate_batch, evaluate_record


def test_rule_geo_001_record_conservation():
    """RULE-GEO-001: Record conservation strictly requires raw == cleaned + quarantined."""
    records = [
        {
            "aircraft_hex_id": "800101",
            "latitude": 19.0,
            "longitude": 72.8,
            "is_on_ground": False,
            "provenance": {"source_url": "https://api.adsb.lol", "raw_acquisition_utc": "2026-10-15T00:00:00Z"}
        }
    ]
    # Evaluate with mismatched raw count (e.g. raw=5 but records=1)
    res = evaluate_batch(records, raw_count=5)
    assert res["conservation_verified"] is False
    assert any(e["rule_id"] == "RULE-GEO-001" for e in res["exceptions"])
    assert res["overall_status"] == "FAIL"

    # Evaluate with matched raw count
    res_pass = evaluate_batch(records, raw_count=1)
    assert res_pass["conservation_verified"] is True
    assert not any(e["rule_id"] == "RULE-GEO-001" for e in res_pass["exceptions"])


def test_rule_geo_002_duplicate_identifiers():
    """RULE-GEO-002: Rejects duplicate aircraft hex addresses in surveillance batch."""
    fixture_path = PROJECT_ROOT / "fixtures" / "invalid_duplicate_records.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    res = evaluate_batch(data["records"])
    assert res["cleaned_record_count"] == 1
    assert res["quarantined_record_count"] == 1
    dup_exceptions = [e for e in res["exceptions"] if e["rule_id"] == "RULE-GEO-002"]
    assert len(dup_exceptions) >= 1
    assert dup_exceptions[0]["severity"] == "HARD_FAILURE"
    assert dup_exceptions[0]["disposition"] == "QUARANTINED"


def test_rule_geo_003_coordinate_bounds():
    """RULE-GEO-003: Coordinates must strictly reside in WGS84 EPSG:4326 envelopes."""
    bad_lat = {
        "aircraft_hex_id": "800102",
        "latitude": 95.0,  # Invalid: > 90
        "longitude": 72.8,
        "is_on_ground": False,
        "provenance": {"source_url": "https://api.adsb.lol", "raw_acquisition_utc": "2026-10-15T00:00:00Z"}
    }
    hard_fails, _ = evaluate_record(bad_lat, 0, set())
    assert any(hf["rule_id"] == "RULE-GEO-003" and "latitude" in hf["field"] for hf in hard_fails)

    bad_lon = {
        "aircraft_hex_id": "800103",
        "latitude": 19.0,
        "longitude": -195.0,  # Invalid: < -180
        "is_on_ground": False,
        "provenance": {"source_url": "https://api.adsb.lol", "raw_acquisition_utc": "2026-10-15T00:00:00Z"}
    }
    hard_fails, _ = evaluate_record(bad_lon, 0, set())
    assert any(hf["rule_id"] == "RULE-GEO-003" and "longitude" in hf["field"] for hf in hard_fails)


def test_rule_geo_004_kinematic_envelopes():
    """RULE-GEO-004: Speeds, altitudes, and tracks must be within physical aviation envelopes."""
    bad_kinematics = {
        "aircraft_hex_id": "800104",
        "latitude": 19.0,
        "longitude": 72.8,
        "is_on_ground": False,
        "ground_speed_kts": 3200.0,  # Impossible civil speed
        "altitude_baro_ft": 95000,    # Exceeds max ceiling
        "true_track_deg": 410.0,      # > 360 degrees
        "provenance": {"source_url": "https://api.adsb.lol", "raw_acquisition_utc": "2026-10-15T00:00:00Z"}
    }
    hard_fails, _ = evaluate_record(bad_kinematics, 0, set())
    rule_ids = [hf["rule_id"] for hf in hard_fails]
    assert rule_ids.count("RULE-GEO-004") == 3


def test_rule_geo_005_temporal_integrity_and_staleness():
    """RULE-GEO-005: Negative latency is a HARD_FAILURE; latency > 300s is a WARNING (STALE)."""
    # Negative latency -> HARD_FAILURE
    negative_latency = {
        "aircraft_hex_id": "800105",
        "latitude": 19.0,
        "longitude": 72.8,
        "is_on_ground": False,
        "last_seen_seconds": -15.0,
        "provenance": {"source_url": "https://api.adsb.lol", "raw_acquisition_utc": "2026-10-15T00:00:00Z"}
    }
    hard_fails, warnings = evaluate_record(negative_latency, 0, set())
    assert any(hf["rule_id"] == "RULE-GEO-005" for hf in hard_fails)

    # Stale latency (>300s) -> WARNING (retained, not quarantined)
    stale_latency = {
        "aircraft_hex_id": "800106",
        "latitude": 19.0,
        "longitude": 72.8,
        "is_on_ground": False,
        "last_seen_seconds": 450.0,
        "provenance": {"source_url": "https://api.adsb.lol", "raw_acquisition_utc": "2026-10-15T00:00:00Z"}
    }
    hard_fails, warnings = evaluate_record(stale_latency, 0, set())
    assert len(hard_fails) == 0
    assert any(w["rule_id"] == "RULE-GEO-005" and w["severity"] == "WARNING" for w in warnings)


def test_rule_geo_006_provenance_completeness():
    """RULE-GEO-006: Provenance must contain source_url and raw_acquisition_utc."""
    fixture_path = PROJECT_ROOT / "fixtures" / "invalid_missing_provenance.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    res = evaluate_batch(data["records"])
    assert res["quarantined_record_count"] == 2
    prov_exceptions = [e for e in res["exceptions"] if e["rule_id"] == "RULE-GEO-006"]
    assert len(prov_exceptions) >= 2


def test_rule_geo_007_schema_conformance():
    """RULE-GEO-007: Mandatory schema attributes must not be missing or malformed."""
    fixture_path = PROJECT_ROOT / "fixtures" / "invalid_schema_mismatch.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    res = evaluate_batch(data["records"])
    assert res["quarantined_record_count"] == 2
    schema_exceptions = [e for e in res["exceptions"] if e["rule_id"] == "RULE-GEO-007"]
    assert len(schema_exceptions) >= 2


def test_rule_geo_008_surface_measurement_consistency():
    """RULE-GEO-008: Inconsistent surface states (e.g. ground flag at 35,000 ft) are quarantined."""
    fixture_path = PROJECT_ROOT / "fixtures" / "invalid_inconsistent_measurements.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    res = evaluate_batch(data["records"])
    assert res["quarantined_record_count"] == 2
    rule8_exceptions = [e for e in res["exceptions"] if e["rule_id"] == "RULE-GEO-008"]
    assert len(rule8_exceptions) >= 1
    assert rule8_exceptions[0]["severity"] == "HARD_FAILURE"


def test_rule_geo_009_dataset_identity_vs_schema_disambiguation():
    """RULE-GEO-009: Dataset ID must not be identical to schema version."""
    ambiguous_meta = {
        "dataset_id": "1.0.0",
        "schema_version": "1.0.0",
        "licence": "Open Data Commons Open Database License (ODbL) v1.0"
    }
    records = [
        {
            "aircraft_hex_id": "800107",
            "latitude": 19.0,
            "longitude": 72.8,
            "is_on_ground": False,
            "provenance": {"source_url": "https://api.adsb.lol", "raw_acquisition_utc": "2026-10-15T00:00:00Z"}
        }
    ]
    res = evaluate_batch(records, dataset_metadata=ambiguous_meta)
    assert any(e["rule_id"] == "RULE-GEO-009" for e in res["exceptions"])


def test_rule_geo_010_license_compliance():
    """RULE-GEO-010: Dataset must declare valid ODbL v1.0 open licensing."""
    invalid_licence_meta = {
        "dataset_id": "BHIV-GEO-QUEST-01-AIRCRAFT",
        "schema_version": "1.0.0",
        "licence": "Proprietary All Rights Reserved"
    }
    records = [
        {
            "aircraft_hex_id": "800108",
            "latitude": 19.0,
            "longitude": 72.8,
            "is_on_ground": False,
            "provenance": {"source_url": "https://api.adsb.lol", "raw_acquisition_utc": "2026-10-15T00:00:00Z"}
        }
    ]
    res = evaluate_batch(records, dataset_metadata=invalid_licence_meta)
    assert any(e["rule_id"] == "RULE-GEO-010" for e in res["exceptions"])


def test_valid_synthetic_aircraft_fixture():
    """Tests that valid synthetic fixture passes 100% of checks with zero exceptions."""
    fixture_path = PROJECT_ROOT / "fixtures" / "valid_synthetic_aircraft.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta = {
        "dataset_id": data["dataset_id"],
        "schema_version": "1.0.0",
        "licence": "Open Data Commons Open Database License (ODbL) v1.0"
    }
    res = evaluate_batch(data["records"], dataset_metadata=meta)
    assert res["overall_status"] == "PASS"
    assert res["cleaned_record_count"] == 3
    assert res["quarantined_record_count"] == 0
    assert len(res["exceptions"]) == 0
