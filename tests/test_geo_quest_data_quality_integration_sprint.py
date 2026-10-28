"""
BHIV vNEXT MASTERDB Data-Quality Integration Sprint Tests
Assigned to: Hariom Upadhyay
Platform Owner: Kavy Changela
Reviewers: Harsha Pawar, Karan

Scope:
- Synthetic test data ONLY (no live aircraft feeds as new inputs)
- Clear categorization:
  1. Unit tests (quality rules, schema, provenance, exceptions, exact record accounting)
  2. Mocked/isolated integration tests (GeoQuestCandidateService with synthetic project root)
  3. Tests against actual supported MASTERDB interfaces (FastAPI endpoints, RBAC, MDU adapter)
  4. Governance boundary tests (canonical isolation, tamper rejection)
"""

import hashlib
import json
from pathlib import Path
import shutil
import sys
import pytest
from fastapi.testclient import TestClient

import main
from main import app, mdu_contract_adapter
from geo_quest_candidate.service import (
    CAPABILITY_ID,
    DATASET_ID,
    GeoQuestCandidateService,
    CandidateRegistrationError,
    CandidateNotFoundError,
    CandidateRetrieveRequest,
)
from services.artifact_store import ArtifactStore
from services.mdu_contract_adapter import MDUContractAdapter

PROJECT_ROOT = Path(__file__).resolve().parent.parent / "MASTERDB-GEO-QUEST-01"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.rule_evaluator import evaluate_batch, evaluate_record


client = TestClient(app)


def _get_admin_token(client_instance: TestClient) -> str:
    response = client_instance.post(
        "/auth/token",
        json={"actor": "admin", "roles": ["bhiv-admin"], "password": "test-admin-password"},
    )
    assert response.status_code == 200, f"Token request failed: {response.text}"
    return response.json()["access_token"]


def _get_viewer_token(client_instance: TestClient) -> str:
    response = client_instance.post(
        "/auth/token",
        json={"actor": "test-viewer", "roles": ["ecosystem-reader"], "password": "test-admin-password"},
    )
    assert response.status_code == 200, f"Token request failed: {response.text}"
    return response.json()["access_token"]


# ==============================================================================
# CATEGORY 1: UNIT TESTS - SYNTHETIC DATA QUALITY, RULES & RECORD ACCOUNTING
# ==============================================================================

class TestSyntheticDataQualityUnit:
    """Verifies rules RULE-GEO-001 through RULE-GEO-010 using synthetic fixtures only."""

    def test_synthetic_valid_fixture_baseline(self):
        """
        Independent verification of valid_synthetic_aircraft.json:
        - Input: 3 records
        - Expected: 3 Cleaned, 0 Quarantined, 0 Hard Failures, 0 Warnings
        - Conservation: 3 == 3 + 0
        """
        fixture_path = PROJECT_ROOT / "fixtures" / "valid_synthetic_aircraft.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        records = data["records"]
        assert len(records) == 3, f"Expected 3 synthetic records, got {len(records)}"

        metadata = {
            "dataset_id": data["dataset_id"],
            "schema_version": "1.0.0",
            "licence": "Open Data Commons Open Database License (ODbL) v1.0",
        }
        res = evaluate_batch(records, raw_count=3, dataset_metadata=metadata)

        assert res["overall_status"] == "PASS"
        assert res["cleaned_record_count"] == 3
        assert res["quarantined_record_count"] == 0
        assert res["hard_failure_count"] == 0
        assert res["warning_count"] == 0
        assert res["conservation_verified"] is True
        assert len(res["exceptions"]) == 0

    def test_synthetic_duplicate_records_accounting(self):
        """
        invalid_duplicate_records.json:
        - Input: 2 records sharing hex identifier '8005A6'
        - Expected: 1 Cleaned (first observed), 1 Quarantined (duplicate)
        - Conservation: 2 == 1 + 1
        - Triggered rule: RULE-GEO-002 (HARD_FAILURE)
        """
        fixture_path = PROJECT_ROOT / "fixtures" / "invalid_duplicate_records.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        records = data["records"]
        assert len(records) == 2

        # Verify individual per-record evaluation contract
        seen = set()
        hf0, w0 = evaluate_record(records[0], 0, seen)
        assert len(hf0) == 0, f"First record must be accepted clean, got: {hf0}"
        assert len(w0) == 0

        hf1, w1 = evaluate_record(records[1], 1, seen)
        assert len(hf1) == 1
        assert hf1[0]["rule_id"] == "RULE-GEO-002"
        assert hf1[0]["severity"] == "HARD_FAILURE"
        assert hf1[0]["disposition"] == "QUARANTINED"
        assert hf1[0]["field"] == "aircraft_hex_id"
        assert hf1[0]["actual_value"] == "8005A6"

        # Verify batch evaluation
        res = evaluate_batch(records)
        assert res["cleaned_record_count"] == 1
        assert res["quarantined_record_count"] == 1
        assert res["conservation_verified"] is True
        assert len(records) == res["cleaned_record_count"] + res["quarantined_record_count"]

        dup_ex = [e for e in res["exceptions"] if e["rule_id"] == "RULE-GEO-002"]
        assert len(dup_ex) == 1
        assert dup_ex[0]["severity"] == "HARD_FAILURE"
        assert dup_ex[0]["disposition"] == "QUARANTINED"
        assert dup_ex[0]["record_id"] == "8005A6"

    def test_synthetic_missing_provenance_accounting(self):
        """
        invalid_missing_provenance.json:
        - Input: 2 records:
          * Record 0 (8005A4): null provenance dictionary -> triggers RULE-GEO-007 (mandatory field)
            and RULE-GEO-006 (missing audit provenance block)
          * Record 1 (8005A5): incomplete provenance -> triggers RULE-GEO-006 twice
            (missing source_url, missing raw_acquisition_utc)
        - Expected: 0 Cleaned, 2 Quarantined
        - Conservation: 2 == 0 + 2
        - Total Exceptions: 4 (all HARD_FAILURE, QUARANTINED)
        - Triggered rules: RULE-GEO-006, RULE-GEO-007
        """
        fixture_path = PROJECT_ROOT / "fixtures" / "invalid_missing_provenance.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        records = data["records"]
        assert len(records) == 2

        # Verify per-record evaluation
        seen = set()
        hf0, _ = evaluate_record(records[0], 0, seen)
        rules_r0 = {e["rule_id"] for e in hf0}
        assert rules_r0 == {"RULE-GEO-006", "RULE-GEO-007"}
        assert any(e["field"] == "provenance" and e["rule_id"] == "RULE-GEO-007" for e in hf0)
        assert any(e["field"] == "provenance" and e["rule_id"] == "RULE-GEO-006" for e in hf0)

        hf1, _ = evaluate_record(records[1], 1, seen)
        rules_r1 = {e["rule_id"] for e in hf1}
        assert rules_r1 == {"RULE-GEO-006"}
        fields_r1 = {e["field"] for e in hf1}
        assert fields_r1 == {"provenance.source_url", "provenance.raw_acquisition_utc"}

        # Verify batch evaluation
        res = evaluate_batch(records)
        assert res["cleaned_record_count"] == 0
        assert res["quarantined_record_count"] == 2
        assert res["conservation_verified"] is True
        assert len(records) == res["cleaned_record_count"] + res["quarantined_record_count"]
        assert len(res["exceptions"]) == 4

        triggered_rules = {e["rule_id"] for e in res["exceptions"]}
        assert triggered_rules == {"RULE-GEO-006", "RULE-GEO-007"}
        assert all(e["severity"] == "HARD_FAILURE" for e in res["exceptions"])
        assert all(e["disposition"] == "QUARANTINED" for e in res["exceptions"])

    def test_synthetic_schema_mismatch_accounting(self):
        """
        invalid_schema_mismatch.json:
        - Input: 2 records:
          * Record 0: missing aircraft_hex_id, null latitude, null longitude -> 3 exceptions
          * Record 1: null aircraft_hex_id -> 1 exception
        - Expected: 0 Cleaned, 2 Quarantined
        - Conservation: 2 == 0 + 2
        - Total Exceptions: 4 (all HARD_FAILURE, QUARANTINED, all RULE-GEO-007)
        - Note on RULE-GEO-003: Coordinate bound checks evaluate non-null numbers;
          null coordinate fields are captured directly as mandatory schema violations by RULE-GEO-007.
        """
        fixture_path = PROJECT_ROOT / "fixtures" / "invalid_schema_mismatch.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        records = data["records"]
        assert len(records) == 2

        # Verify per-record evaluation
        seen = set()
        hf0, _ = evaluate_record(records[0], 0, seen)
        assert len(hf0) == 3
        fields_r0 = {e["field"] for e in hf0}
        assert fields_r0 == {"aircraft_hex_id", "latitude", "longitude"}
        assert all(e["rule_id"] == "RULE-GEO-007" for e in hf0)

        hf1, _ = evaluate_record(records[1], 1, seen)
        assert len(hf1) == 1
        assert hf1[0]["field"] == "aircraft_hex_id"
        assert hf1[0]["rule_id"] == "RULE-GEO-007"

        # Verify batch evaluation
        res = evaluate_batch(records)
        assert res["cleaned_record_count"] == 0
        assert res["quarantined_record_count"] == 2
        assert res["conservation_verified"] is True
        assert len(records) == res["cleaned_record_count"] + res["quarantined_record_count"]
        assert len(res["exceptions"]) == 4

        triggered_rules = {e["rule_id"] for e in res["exceptions"]}
        assert triggered_rules == {"RULE-GEO-007"}
        assert all(e["severity"] == "HARD_FAILURE" for e in res["exceptions"])
        assert all(e["disposition"] == "QUARANTINED" for e in res["exceptions"])

    def test_synthetic_malformed_field_types_accounting(self):
        """
        invalid_malformed_field_types.json:
        - Input: 1 record ('NOT_A_VALID_HEX_LONGER_THAN_6_CHARS_!'):
          * Invalid hex format (longer than 6 chars) -> RULE-GEO-002
          * String latitude ('nineteen_degrees_north') -> RULE-GEO-003
          * String ground speed ('fast') -> RULE-GEO-004
          * Array altitude ([35000]) -> RULE-GEO-004
        - Expected: 0 Cleaned, 1 Quarantined
        - Conservation: 1 == 0 + 1
        - Total Exceptions: 4 (all HARD_FAILURE, QUARANTINED)
        - Triggered rules: RULE-GEO-002, RULE-GEO-003, RULE-GEO-004
        """
        fixture_path = PROJECT_ROOT / "fixtures" / "invalid_malformed_field_types.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        records = data["records"]
        assert len(records) == 1

        # Verify per-record evaluation
        seen = set()
        hf, warnings = evaluate_record(records[0], 0, seen)
        assert len(hf) == 4
        assert len(warnings) == 0

        rules = {e["rule_id"] for e in hf}
        assert rules == {"RULE-GEO-002", "RULE-GEO-003", "RULE-GEO-004"}
        fields = {e["field"] for e in hf}
        assert fields == {"aircraft_hex_id", "latitude", "ground_speed_kts", "altitude_baro_ft"}

        # Verify batch evaluation
        res = evaluate_batch(records)
        assert res["cleaned_record_count"] == 0
        assert res["quarantined_record_count"] == 1
        assert res["conservation_verified"] is True
        assert len(records) == res["cleaned_record_count"] + res["quarantined_record_count"]
        assert len(res["exceptions"]) == 4

        for exc in res["exceptions"]:
            assert exc["severity"] == "HARD_FAILURE"
            assert exc["disposition"] == "QUARANTINED"
            assert exc["record_id"] == "NOT_A_VALID_HEX_LONGER_THAN_6_CHARS_!"

    def test_synthetic_inconsistent_measurements_accounting(self):
        """
        invalid_inconsistent_measurements.json:
        - Input: 2 records:
          * Record 0 (8005A9): on ground but reporting 35000 ft altitude (> 500 ft)
            and 450 kts speed (> 200 kts) -> 2 exceptions for RULE-GEO-008
          * Record 1 (8005AA): supersonic ground speed 2500 kts (> 1500 kts) -> 1 exception for RULE-GEO-004
        - Expected: 0 Cleaned, 2 Quarantined
        - Conservation: 2 == 0 + 2
        - Total Exceptions: 3 (all HARD_FAILURE, QUARANTINED)
        - Triggered rules: RULE-GEO-004, RULE-GEO-008
        """
        fixture_path = PROJECT_ROOT / "fixtures" / "invalid_inconsistent_measurements.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        records = data["records"]
        assert len(records) == 2

        # Verify per-record evaluation
        seen = set()
        hf0, _ = evaluate_record(records[0], 0, seen)
        assert len(hf0) == 2
        assert all(e["rule_id"] == "RULE-GEO-008" for e in hf0)
        fields_r0 = {e["field"] for e in hf0}
        assert fields_r0 == {"altitude_baro_ft", "ground_speed_kts"}

        hf1, _ = evaluate_record(records[1], 1, seen)
        assert len(hf1) == 1
        assert hf1[0]["rule_id"] == "RULE-GEO-004"
        assert hf1[0]["field"] == "ground_speed_kts"
        assert hf1[0]["actual_value"] == 2500.0

        # Verify batch evaluation
        res = evaluate_batch(records)
        assert res["cleaned_record_count"] == 0
        assert res["quarantined_record_count"] == 2
        assert res["conservation_verified"] is True
        assert len(records) == res["cleaned_record_count"] + res["quarantined_record_count"]
        assert len(res["exceptions"]) == 3

        triggered_rules = {e["rule_id"] for e in res["exceptions"]}
        assert triggered_rules == {"RULE-GEO-004", "RULE-GEO-008"}
        assert all(e["severity"] == "HARD_FAILURE" for e in res["exceptions"])
        assert all(e["disposition"] == "QUARANTINED" for e in res["exceptions"])

    def test_synthetic_stale_data_and_warning_accounting(self):
        """
        invalid_stale_data.json:
        - Input: 2 records:
          * Record 0 (8005A7): negative last_seen_seconds (-5.2s) & position_age_seconds (-1.0s) -> 2 hard failures
          * Record 1 (8005A8): last_seen_seconds (650s) & position_age_seconds (620s) > 300s -> 2 warnings
        - Expected: 1 Cleaned (stale warning retained), 1 Quarantined (negative latency hard fail)
        - Conservation: 2 == 1 + 1
        - Warning count == 2, Hard failure count == 2
        """
        fixture_path = PROJECT_ROOT / "fixtures" / "invalid_stale_data.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        records = data["records"]
        assert len(records) == 2

        # Verify per-record evaluation
        seen = set()
        hf0, w0 = evaluate_record(records[0], 0, seen)
        assert len(hf0) == 2
        assert len(w0) == 0
        assert all(e["rule_id"] == "RULE-GEO-005" for e in hf0)
        assert all(e["severity"] == "HARD_FAILURE" for e in hf0)

        hf1, w1 = evaluate_record(records[1], 1, seen)
        assert len(hf1) == 0
        assert len(w1) == 2
        assert all(e["rule_id"] == "RULE-GEO-005" for e in w1)
        assert all(e["severity"] == "WARNING" for e in w1)
        assert all(e["disposition"] == "FLAGGED_STALE" for e in w1)

        # Verify batch evaluation
        res = evaluate_batch(records)
        assert res["cleaned_record_count"] == 1
        assert res["quarantined_record_count"] == 1
        assert res["hard_failure_count"] == 2
        assert res["warning_count"] == 2
        assert res["conservation_verified"] is True
        assert len(records) == res["cleaned_record_count"] + res["quarantined_record_count"]

    def test_cumulative_synthetic_failure_accounting_equation(self):
        """
        Cumulative independent verification of all 6 negative failure scenarios:
        - Total Failure Records = 2 + 2 + 1 + 2 + 2 + 2 = 11 records
        - Total Cleaned = 1 (duplicate baseline) + 1 (stale warning) = 2
        - Total Quarantined = 1 + 2 + 1 + 2 + 2 + 1 = 9
        - Total Hard Failures = 1 + 4 + 4 + 4 + 3 + 2 = 18 hard failures
        - Total Warnings = 0 + 0 + 0 + 0 + 0 + 2 = 2 warnings
        - Total Cumulative Exceptions = 18 + 2 = 20 exceptions
        - Strict Conservation: 11 == 2 + 9
        """
        fixture_files = [
            "fixtures/invalid_duplicate_records.json",
            "fixtures/invalid_missing_provenance.json",
            "fixtures/invalid_schema_mismatch.json",
            "fixtures/invalid_malformed_field_types.json",
            "fixtures/invalid_inconsistent_measurements.json",
            "fixtures/invalid_stale_data.json",
        ]
        total_input = 0
        total_cleaned = 0
        total_quarantined = 0
        total_hard_failures = 0
        total_warnings = 0

        for rel_path in fixture_files:
            with open(PROJECT_ROOT / rel_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            rec = d["records"]
            total_input += len(rec)
            res = evaluate_batch(rec)
            total_cleaned += res["cleaned_record_count"]
            total_quarantined += res["quarantined_record_count"]
            total_hard_failures += res["hard_failure_count"]
            total_warnings += res["warning_count"]

        assert total_input == 11, f"Expected 11 failure records, got {total_input}"
        assert total_cleaned == 2, f"Expected 2 cleaned records, got {total_cleaned}"
        assert total_quarantined == 9, f"Expected 9 quarantined records, got {total_quarantined}"
        assert total_input == total_cleaned + total_quarantined
        assert total_hard_failures == 18
        assert total_warnings == 2
        assert (total_hard_failures + total_warnings) == 20

    def test_synthetic_rule_geo_001_record_conservation_failure(self):
        """RULE-GEO-001: Mathematical record conservation rejection when counts mismatch."""
        valid_fixture = PROJECT_ROOT / "fixtures" / "valid_synthetic_aircraft.json"
        with open(valid_fixture, "r", encoding="utf-8") as f:
            data = json.load(f)
        records = data["records"]  # 3 records

        # Declare raw_count as 5 when only 3 records are provided
        res = evaluate_batch(records, raw_count=5)
        assert res["conservation_verified"] is False
        cons_ex = [e for e in res["exceptions"] if e["rule_id"] == "RULE-GEO-001"]
        assert len(cons_ex) == 1
        assert cons_ex[0]["severity"] == "HARD_FAILURE"
        assert cons_ex[0]["disposition"] == "REJECT_BATCH"

    def test_synthetic_rule_geo_003_coordinate_bounds(self):
        """RULE-GEO-003: Coordinate WGS84 range validation [-90, +90] and [-180, +180]."""
        seen = set()
        bad_lat = {
            "aircraft_hex_id": "8005B1",
            "latitude": 95.5,
            "longitude": 72.8,
            "is_on_ground": False,
            "provenance": {"source_url": "https://geo-quest-synthetic.invalid/feed", "raw_acquisition_utc": "2026-10-15T09:45:00Z"},
        }
        hf_lat, _ = evaluate_record(bad_lat, 0, seen)
        assert any(e["rule_id"] == "RULE-GEO-003" and e["field"] == "latitude" for e in hf_lat)

        bad_lon = {
            "aircraft_hex_id": "8005B2",
            "latitude": 19.0,
            "longitude": -195.0,
            "is_on_ground": False,
            "provenance": {"source_url": "https://geo-quest-synthetic.invalid/feed", "raw_acquisition_utc": "2026-10-15T09:45:00Z"},
        }
        hf_lon, _ = evaluate_record(bad_lon, 1, seen)
        assert any(e["rule_id"] == "RULE-GEO-003" and e["field"] == "longitude" for e in hf_lon)

    def test_synthetic_rule_geo_009_dataset_identity_disambiguation(self):
        """RULE-GEO-009: Dataset ID must not equal schema version."""
        records = [{
            "aircraft_hex_id": "8005B3",
            "latitude": 19.0,
            "longitude": 72.8,
            "is_on_ground": False,
            "provenance": {"source_url": "https://geo-quest-synthetic.invalid/feed", "raw_acquisition_utc": "2026-10-15T09:45:00Z"},
        }]
        res = evaluate_batch(records, dataset_metadata={"dataset_id": "1.0.0", "schema_version": "1.0.0", "licence": "ODbL"})
        rule_9 = [e for e in res["exceptions"] if e["rule_id"] == "RULE-GEO-009"]
        assert len(rule_9) == 1
        assert rule_9[0]["severity"] == "HARD_FAILURE"
        assert rule_9[0]["disposition"] == "REJECT_PAYLOAD"

    def test_synthetic_rule_geo_010_license_compliance(self):
        """RULE-GEO-010: Dataset must declare compliant ODbL v1.0 license."""
        records = [{
            "aircraft_hex_id": "8005B4",
            "latitude": 19.0,
            "longitude": 72.8,
            "is_on_ground": False,
            "provenance": {"source_url": "https://geo-quest-synthetic.invalid/feed", "raw_acquisition_utc": "2026-10-15T09:45:00Z"},
        }]
        res = evaluate_batch(records, dataset_metadata={"dataset_id": "DS-001", "schema_version": "1.0.0", "licence": "Proprietary Commercial"})
        rule_10 = [e for e in res["exceptions"] if e["rule_id"] == "RULE-GEO-010"]
        assert len(rule_10) == 1
        assert rule_10[0]["severity"] == "HARD_FAILURE"
        assert rule_10[0]["disposition"] == "REJECT_ASSET"


# ==============================================================================
# CATEGORY 2: MOCKED/ISOLATED INTEGRATION TESTS (GeoQuestCandidateService)
# ==============================================================================

def _setup_isolated_synthetic_workspace(tmp_path: Path) -> Path:
    """Builds a temporary, isolated synthetic project root strictly using synthetic fixtures."""
    fake_root = tmp_path / "synthetic_project_root"
    shutil.copytree(PROJECT_ROOT / "registration", fake_root / "registration")
    shutil.copytree(PROJECT_ROOT / "metadata", fake_root / "metadata")
    shutil.copytree(PROJECT_ROOT / "validation", fake_root / "validation")
    shutil.copytree(PROJECT_ROOT / "scripts", fake_root / "scripts")
    (fake_root / "raw").mkdir()
    (fake_root / "cleaned").mkdir()

    # Load 3 synthetic records
    valid_fixture = PROJECT_ROOT / "fixtures" / "valid_synthetic_aircraft.json"
    with open(valid_fixture, "r", encoding="utf-8") as f:
        synth_data = json.load(f)

    # Extract accurate synthetic acquisition metadata from synthetic fixture
    synth_records = synth_data["records"]
    endpoint = "https://geo-quest-synthetic.invalid/v2/lat/19.0760/lon/72.8777/dist/100"
    acquired_at = synth_data.get("generated_at_utc", "2026-10-15T09:45:00Z")

    # Update dataset_record counts and synthetic provenance to 3
    ds_rec_path = fake_root / "registration" / "dataset_record.json"
    ds_rec = json.loads(ds_rec_path.read_text(encoding="utf-8"))
    ds_rec["source_reference"]["endpoint"] = endpoint
    ds_rec["acquisition_timestamp_utc"] = acquired_at
    ds_rec["cleaning_pipeline_utc"] = acquired_at
    ds_rec["record_counts"]["raw_record_count"] = 3
    ds_rec["record_counts"]["cleaned_record_count"] = 3
    ds_rec["record_counts"]["quarantined_record_count"] = 0
    ds_rec["record_counts"]["total_governed_records"] = 3
    ds_rec["governance_notice"]["synthetic_test_data"] = True
    ds_rec["governance_notice"]["live_data_collected"] = False
    ds_rec_path.write_text(json.dumps(ds_rec, indent=2), encoding="utf-8")

    # Update source_record to synthetic endpoint and timestamp
    src_rec_path = fake_root / "registration" / "source_record.json"
    src_rec = json.loads(src_rec_path.read_text(encoding="utf-8"))
    src_rec["endpoint_used"] = endpoint
    src_rec["exact_acquisition_timestamp_utc"] = acquired_at
    src_rec["synthetic_data"] = True
    src_rec_path.write_text(json.dumps(src_rec, indent=2), encoding="utf-8")

    # Update metadata counts and synthetic provenance to 3
    meta_doc_path = fake_root / "metadata" / "aircraft_metadata.json"
    meta_doc = json.loads(meta_doc_path.read_text(encoding="utf-8"))
    meta_doc["source_url"] = endpoint
    meta_doc["collection_timestamp_utc"] = acquired_at
    meta_doc["raw_record_count"] = 3
    meta_doc["cleaned_record_count"] = 3
    meta_doc["synthetic_data"] = True
    meta_doc_path.write_text(json.dumps(meta_doc, indent=2), encoding="utf-8")

    # Update quality report counts to 3
    qr_path = fake_root / "validation" / "aircraft_quality_report.json"
    qr = json.loads(qr_path.read_text(encoding="utf-8"))
    qr["record_counts"]["raw_record_count"] = 3
    qr["record_counts"]["cleaned_record_count"] = 3
    qr["record_counts"]["quarantined_record_count"] = 0
    qr["synthetic_data"] = True
    for chk in qr.get("executed_checks", []):
        if chk["check_id"] == "CHK_01_RECORD_CONSERVATION":
            chk["details"]["raw_count"] = 3
            chk["details"]["cleaned_count"] = 3
            chk["details"]["sum_cleaned_quarantine"] = 3
        elif chk["check_id"] == "CHK_02_IDENTIFIER_UNIQUENESS":
            chk["details"]["total_cleaned_identifiers"] = 3
            chk["details"]["unique_identifiers"] = 3
        elif chk["check_id"] == "CHK_03_COORDINATE_VALIDITY":
            chk["details"]["records_evaluated"] = 3
    qr_path.write_text(json.dumps(qr, indent=2), encoding="utf-8")

    raw_ac = []
    for r in synth_records:
        raw_ac.append({
            "hex": r["aircraft_hex_id"],
            "flight": r.get("callsign", ""),
            "r": r.get("registration", ""),
            "t": r.get("aircraft_type_icao", ""),
            "squawk": r.get("squawk_code", ""),
            "category": r.get("emitter_category", ""),
            "lat": r["latitude"],
            "lon": r["longitude"],
            "alt_baro": "ground" if r.get("is_on_ground") else r.get("altitude_baro_ft"),
            "alt_geom": r.get("altitude_geom_ft"),
            "gs": r.get("ground_speed_kts"),
            "track": r.get("true_track_deg"),
            "baro_rate": r.get("vertical_rate_fpm"),
            "seen": r.get("last_seen_seconds"),
            "seen_pos": r.get("position_age_seconds"),
            "dst": r.get("distance_from_center_nm"),
            "dir": r.get("bearing_from_center_deg"),
            "rssi": r.get("signal_rssi_db"),
        })

    raw_path = fake_root / "raw" / "aircraft_raw.json"
    meta_path = fake_root / "raw" / "acquisition_metadata.json"
    cleaned_path = fake_root / "cleaned" / "aircraft_cleaned.json"
    quarantine_path = fake_root / "cleaned" / "aircraft_quarantine.json"

    raw_path.write_text(json.dumps({"ac": raw_ac, "total": len(raw_ac), "now": 1760521500.0}, indent=2), encoding="utf-8")
    meta_path.write_text(json.dumps({
        "status": "SUCCESS",
        "http_status": 200,
        "live_data_collected": False,
        "synthetic_data": True,
        "source_url": endpoint,
        "utc_acquisition_timestamp": acquired_at,
        "generator": "valid_synthetic_aircraft.json",
    }, indent=2), encoding="utf-8")

    from scripts.clean_aircraft import clean_and_normalize_dataset
    clean_and_normalize_dataset(str(raw_path), str(meta_path), str(cleaned_path), str(quarantine_path))

    return fake_root


class TestIsolatedCandidateServiceIntegration:
    """Tests GeoQuestCandidateService using the isolated synthetic project workspace."""

    def test_synthetic_candidate_registration_and_hashing(self, tmp_path):
        fake_root = _setup_isolated_synthetic_workspace(tmp_path)
        store_dir = tmp_path / "store"
        service = GeoQuestCandidateService(store_dir=str(store_dir), project_root=fake_root)

        assert isinstance(service.store, ArtifactStore)

        summary = service.register_candidate(actor="synthetic-runner")

        assert summary["capability_id"] == CAPABILITY_ID
        assert summary["dataset_id"] == DATASET_ID
        assert summary["registration_status"] == "PENDING_AUTHORIZATION"
        assert summary["canonical"] is False
        assert summary["discoverable"] is False
        assert summary["record_count"] == 3

        # Verify stored bundle integrity and exact SHA-256 computation
        loaded = service.store.load(CAPABILITY_ID)
        assert loaded is not None
        assert loaded["registered_by"] == "synthetic-runner"
        assert len(loaded["records"]) == 3
        assert loaded["dataset"]["proposed_dataset_id"] == "BHIV-GEO-QUEST-01-AIRCRAFT"

        # Independently verify SHA-256 digest computation using hashlib
        payload = {k: v for k, v in loaded.items() if k != "bundle_sha256"}
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        expected_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        assert loaded["bundle_sha256"] == expected_hash

    def test_synthetic_candidate_retrieval_and_filtering(self, tmp_path):
        fake_root = _setup_isolated_synthetic_workspace(tmp_path)
        store_dir = tmp_path / "store"
        service = GeoQuestCandidateService(store_dir=str(store_dir), project_root=fake_root)
        service.register_candidate(actor="synthetic-runner")

        # 1. Unfiltered retrieval (within 100 NM of Mumbai FIR)
        req_all = CandidateRetrieveRequest(center_latitude=19.076, center_longitude=72.8777, search_radius_nm=100)
        res_all = service.retrieve(CAPABILITY_ID, req_all)
        assert res_all["capability"]["discoverable"] is False
        assert res_all["query_metadata"]["matched_record_count"] == 3
        assert len(res_all["records"]) == 3

        # 2. Filter by callsign 'AIC101'
        req_callsign = CandidateRetrieveRequest(
            center_latitude=19.076, center_longitude=72.8777, search_radius_nm=100, filter_callsign="AIC101"
        )
        res_callsign = service.retrieve(CAPABILITY_ID, req_callsign)
        assert res_callsign["query_metadata"]["matched_record_count"] == 1
        assert res_callsign["records"][0]["callsign"] == "AIC101"
        assert res_callsign["records"][0]["aircraft_hex_id"] == "8005A1"

        # 3. Filter by hex ID '8005A2'
        req_hex = CandidateRetrieveRequest(
            center_latitude=19.076, center_longitude=72.8777, search_radius_nm=100, filter_hex_id="8005A2"
        )
        res_hex = service.retrieve(CAPABILITY_ID, req_hex)
        assert res_hex["query_metadata"]["matched_record_count"] == 1
        assert res_hex["records"][0]["aircraft_hex_id"] == "8005A2"
        assert res_hex["records"][0]["callsign"] == "IGO202"

        # 4. Spatial boundary verification based on actual coordinates:
        # Distance calculation check:
        # AIC101 is at ~0.941 NM, SEJ303 is at ~0.955 NM, IGO202 is at ~6.083 NM
        # Radius 0.5 NM: All 3 synthetic aircraft are > 0.5 NM away -> 0 matched
        req_narrow = CandidateRetrieveRequest(
            center_latitude=19.076, center_longitude=72.8777, search_radius_nm=0.5
        )
        res_narrow = service.retrieve(CAPABILITY_ID, req_narrow)
        assert res_narrow["query_metadata"]["matched_record_count"] == 0
        assert len(res_narrow["records"]) == 0

        # Radius 1.0 NM: AIC101 (0.941 NM) and SEJ303 (0.955 NM) match -> 2 matched
        req_1nm = CandidateRetrieveRequest(
            center_latitude=19.076, center_longitude=72.8777, search_radius_nm=1.0
        )
        res_1nm = service.retrieve(CAPABILITY_ID, req_1nm)
        assert res_1nm["query_metadata"]["matched_record_count"] == 2
        matched_hexes = {r["aircraft_hex_id"] for r in res_1nm["records"]}
        assert matched_hexes == {"8005A1", "8005A3"}

    def test_synthetic_bundle_tamper_rejection(self, tmp_path):
        fake_root = _setup_isolated_synthetic_workspace(tmp_path)
        store_dir = tmp_path / "store"
        service = GeoQuestCandidateService(store_dir=str(store_dir), project_root=fake_root)
        service.register_candidate(actor="synthetic-runner")

        # Tamper with stored bundle
        loaded = service.store.load(CAPABILITY_ID)
        loaded["records"][0]["aircraft_hex_id"] = "TAMPER"
        service.store.save(CAPABILITY_ID, loaded)

        # Retrieval must fail closed due to SHA-256 hash mismatch
        req = CandidateRetrieveRequest()
        with pytest.raises(CandidateRegistrationError) as exc_info:
            service.retrieve(CAPABILITY_ID, req)
        assert "integrity check" in str(exc_info.value) or "SHA-256" in str(exc_info.value)


# ==============================================================================
# CATEGORY 3: TESTS AGAINST ACTUAL SUPPORTED MASTERDB INTERFACES
# ==============================================================================

class TestSupportedMasterdbInterfaces:
    """Tests the real FastAPI REST API endpoints using the isolated synthetic service."""

    def test_api_candidate_registration_and_retrieval(self, tmp_path, monkeypatch):
        fake_root = _setup_isolated_synthetic_workspace(tmp_path)
        store_dir = tmp_path / "api_store"
        synthetic_service = GeoQuestCandidateService(store_dir=str(store_dir), project_root=fake_root)

        monkeypatch.setenv("AUTH_PASSWORD", "test-admin-password")
        monkeypatch.setattr(main, "geo_quest_candidate_service", synthetic_service)

        admin_token = _get_admin_token(client)
        headers = {"Authorization": f"Bearer {admin_token}"}

        # 1. Register candidate via supported interface
        reg_resp = client.post(
            f"/geo-quest/candidates/{CAPABILITY_ID}/register",
            headers=headers,
        )
        assert reg_resp.status_code == 200
        body = reg_resp.json()
        assert body["capability_id"] == CAPABILITY_ID
        assert body["registration_status"] == "PENDING_AUTHORIZATION"
        assert body["canonical"] is False
        assert body["discoverable"] is False
        assert "mdu_schema_contract" in body
        assert body["mdu_schema_contract"]["dataset_id"] == "BHIV-GEO-QUEST-01-AIRCRAFT"
        assert "mdu_schema_compatibility" in body
        assert body["mdu_schema_compatibility"]["compatible"] is True

        # 2. Get candidate manifest
        manifest_resp = client.get(f"/geo-quest/candidates/{CAPABILITY_ID}", headers=headers)
        assert manifest_resp.status_code == 200
        manifest = manifest_resp.json()
        # Verify proposed upstream source description and synthetic data markings
        assert manifest["source"]["source_name"] == "adsb.lol"
        assert manifest["source"]["synthetic_data"] is True
        assert "geo-quest-synthetic.invalid" in manifest["source"]["endpoint_used"]
        assert manifest["dataset"]["proposed_dataset_id"] == "BHIV-GEO-QUEST-01-AIRCRAFT"
        assert manifest["dataset"]["governance_notice"]["synthetic_test_data"] is True
        assert manifest["dataset"]["governance_notice"]["live_data_collected"] is False

        # 3. Controlled spatial retrieval via supported interface
        retrieve_resp = client.post(
            f"/geo-quest/candidates/{CAPABILITY_ID}/retrieve",
            json={"filter_callsign": "SEJ303"},
            headers=headers,
        )
        assert retrieve_resp.status_code == 200
        retrieval_data = retrieve_resp.json()
        assert retrieval_data["capability"]["discoverable"] is False
        assert retrieval_data["query_metadata"]["matched_record_count"] == 1
        assert retrieval_data["records"][0]["callsign"] == "SEJ303"
        assert retrieval_data["records"][0]["is_on_ground"] is True

    def test_api_rbac_enforcement(self, tmp_path, monkeypatch):
        fake_root = _setup_isolated_synthetic_workspace(tmp_path)
        store_dir = tmp_path / "api_store"
        synthetic_service = GeoQuestCandidateService(store_dir=str(store_dir), project_root=fake_root)

        monkeypatch.setenv("AUTH_PASSWORD", "test-admin-password")
        monkeypatch.setattr(main, "geo_quest_candidate_service", synthetic_service)

        viewer_token = _get_viewer_token(client)
        headers = {"Authorization": f"Bearer {viewer_token}"}

        # Non-admin registration attempt must return 403
        reg_resp = client.post(f"/geo-quest/candidates/{CAPABILITY_ID}/register", headers=headers)
        assert reg_resp.status_code == 403
        reg_err = reg_resp.json().get("detail") or reg_resp.json().get("error", {}).get("message", "")
        assert "Only bhiv-admin may stage GEO-QUEST candidates" in reg_err

        # Non-admin inspection attempt must return 403
        inspect_resp = client.get(f"/geo-quest/candidates/{CAPABILITY_ID}", headers=headers)
        assert inspect_resp.status_code == 403
        inspect_err = inspect_resp.json().get("detail") or inspect_resp.json().get("error", {}).get("message", "")
        assert "Only bhiv-admin may inspect GEO-QUEST candidates" in inspect_err

        # Non-admin retrieval attempt must return 403
        retrieve_resp = client.post(f"/geo-quest/candidates/{CAPABILITY_ID}/retrieve", json={}, headers=headers)
        assert retrieve_resp.status_code == 403
        ret_err = retrieve_resp.json().get("detail") or retrieve_resp.json().get("error", {}).get("message", "")
        assert "Only bhiv-admin may retrieve GEO-QUEST candidates" in ret_err

        # Unauthenticated attempts must return 401
        unauth_resp = client.post(f"/geo-quest/candidates/{CAPABILITY_ID}/register")
        assert unauth_resp.status_code == 401

    def test_canonical_isolation_and_governance_boundary(self, tmp_path, monkeypatch):
        """Ensures that staging a candidate NEVER creates a canonical capability in the main registry."""
        fake_root = _setup_isolated_synthetic_workspace(tmp_path)
        store_dir = tmp_path / "api_store"
        synthetic_service = GeoQuestCandidateService(store_dir=str(store_dir), project_root=fake_root)

        monkeypatch.setenv("AUTH_PASSWORD", "test-admin-password")
        monkeypatch.setattr(main, "geo_quest_candidate_service", synthetic_service)

        admin_token = _get_admin_token(client)
        headers = {"Authorization": f"Bearer {admin_token}"}

        client.post(f"/geo-quest/candidates/{CAPABILITY_ID}/register", headers=headers)

        # Check canonical capability discovery endpoint
        canonical_caps = client.get("/capabilities", headers=headers)
        assert canonical_caps.status_code == 200
        cap_ids = [c["capability_id"] for c in canonical_caps.json()]
        assert CAPABILITY_ID not in cap_ids, f"Candidate {CAPABILITY_ID} leaked into canonical registry!"

        search_caps = client.get("/capabilities?search=gev", headers=headers)
        assert search_caps.status_code == 200
        search_ids = [c["capability_id"] for c in search_caps.json()]
        assert CAPABILITY_ID not in search_ids

    def test_mdu_contract_adapter_integration(self):
        """
        Verifies MDUContractAdapter schema compatibility evaluation and version negotiation
        using the supported MDU contract adapter interface.
        """
        # 1. Unconfigured / placeholder mode fallback behavior
        assert not mdu_contract_adapter.client.is_configured()
        compat = mdu_contract_adapter.validate_schema_compatibility("BHIV-GEO-QUEST-01-AIRCRAFT", "1.0.0")
        assert compat["source"] == "placeholder"
        assert compat["compatible"] is True
        assert "placeholder" in compat["reason"]

        # 2. Version negotiation behavior
        match_res = MDUContractAdapter.negotiate_version("1.0.0", "1.0")
        assert match_res["compatible"] is True

        mismatch_res = MDUContractAdapter.negotiate_version("2.0.0", "1.0")
        assert mismatch_res["compatible"] is False

        missing_res = MDUContractAdapter.negotiate_version("1.0.0", "")
        assert missing_res["compatible"] is False

    def test_tracked_source_store_fixtures_remain_intact(self):
        """Regression test: verifies repository tracked source_store fixtures remain intact."""
        repo_root = Path(__file__).resolve().parent.parent
        source_store_dir = repo_root / "source_store"
        assert source_store_dir.is_dir(), "Repository source_store/ directory must exist"

        expected_fixtures = [
            "src-gev-celestrak.json",
            "src-gev-nifc-firms.json",
            "src-gev-noaa-weather.json",
            "src-gev-usgs-seismic.json",
            "src-marine-intel-ports.json",
        ]
        for fixture_name in expected_fixtures:
            fixture_path = source_store_dir / fixture_name
            assert fixture_path.is_file(), f"Tracked fixture {fixture_name} missing from source_store/"
            content = json.loads(fixture_path.read_text(encoding="utf-8"))
            assert "source_id" in content, f"Fixture {fixture_name} corrupted or missing source_id"
