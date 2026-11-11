"""
Comprehensive Data Integrity & Validation Tests for CMO Marketing Intelligence.
Author: Hariom Upadhyay (MASTERDB Data Integrity Lead)
Role: MASTERDB data integrity and validation specialist for CMO Agent delivery.
"""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

import main
from main import app
from services.cmo_data_validation_service import CMODataValidationService
from tests.identity_fixtures import issue_fixed_test_token as issue_test_token


client = TestClient(app)
ROOT = Path(__file__).resolve().parents[1]
VALID_SAMPLE_PATH = ROOT / "datasets" / "cmo" / "cmo_marketing_sample_valid.json"
FIXTURES_DIR = ROOT / "datasets" / "cmo" / "fixtures"


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def validator():
    return CMODataValidationService(max_freshness_hours=48)


@pytest.fixture
def valid_records():
    data = _load_json(VALID_SAMPLE_PATH)
    return data["records"]


# ---------------------------------------------------------------------------
# Pillar 1: Schema Consistency
# ---------------------------------------------------------------------------


def test_schema_consistency_passes_on_valid_sample(validator, valid_records):
    """Verify clean CMO marketing records conform 100% to declared schema."""
    result = validator.validate_schema_consistency(valid_records)
    assert result["status"] == "PASS"
    assert result["score"] == 100.0
    assert result["violation_count"] == 0
    assert result["violations"] == []


def test_schema_consistency_detects_mismatches(validator):
    """Verify defect sample with invalid types and enums is strictly caught."""
    defect_data = _load_json(FIXTURES_DIR / "cmo_defect_schema_mismatch.json")
    result = validator.validate_schema_consistency(defect_data["records"])

    assert result["status"] == "FAIL"
    assert result["score"] < 100.0
    assert result["violation_count"] >= 3

    errors = [v.get("error", "") for v in result["violations"]]
    # 1. Missing required field 'attribution_model'
    missing_fields_violations = [v for v in result["violations"] if v.get("field") == "missing_fields"]
    assert missing_fields_violations, "Must catch missing required fields"
    assert "attribution_model" in missing_fields_violations[0]["missing"]

    # 2. Invalid channel enum
    channel_violations = [v for v in result["violations"] if v.get("field") == "channel"]
    assert channel_violations, "Must catch invalid channel enum"

    # 3. Non-numeric spend_usd
    spend_violations = [v for v in result["violations"] if v.get("field") == "spend_usd"]
    assert spend_violations, "Must catch string spend_usd"


# ---------------------------------------------------------------------------
# Pillar 2: Freshness & Staleness
# ---------------------------------------------------------------------------


def test_freshness_passes_on_recent_records(validator, valid_records):
    """Verify valid sample records are fresh relative to observation timestamp."""
    # Using fixed as-of anchor matching dataset generation time
    anchor = datetime.fromisoformat("2026-11-06T12:00:00+00:00")
    result = validator.validate_freshness(valid_records, as_of_utc=anchor)
    assert result["status"] == "PASS"
    assert result["score"] == 100.0
    assert result["stale_record_count"] == 0


def test_freshness_detects_stale_records(validator):
    """Verify records older than 48-hour SLA are flagged with exact age."""
    defect_data = _load_json(FIXTURES_DIR / "cmo_defect_stale_freshness.json")
    anchor = datetime.fromisoformat("2026-11-06T12:00:00+00:00")
    result = validator.validate_freshness(defect_data["records"], as_of_utc=anchor)

    assert result["status"] == "FAIL"
    assert result["stale_record_count"] == 1
    assert result["violations"][0]["age_hours"] > 48.0
    assert "exceeds SLA threshold 48" in result["violations"][0]["error"]


def test_freshness_detects_future_timestamps(validator):
    """Verify records with future timestamps are flagged."""
    now = datetime.now(timezone.utc)
    future_record = [
        {
            "campaign_id": "CMP-2026-Q4-001",
            "last_updated_utc": (now + timedelta(days=5)).isoformat(),
        }
    ]
    result = validator.validate_freshness(future_record, as_of_utc=now)
    assert result["status"] == "FAIL"
    assert any("future" in v.get("error", "") for v in result["violations"])


# ---------------------------------------------------------------------------
# Pillar 3: Duplicate Detection
# ---------------------------------------------------------------------------


def test_duplicate_detection_passes_on_unique_records(validator, valid_records):
    """Verify valid sample has zero duplicate campaign IDs and unique rows."""
    result = validator.validate_duplicates(valid_records)
    assert result["status"] == "PASS"
    assert result["score"] == 100.0
    assert result["duplicate_campaign_id_count"] == 0
    assert result["duplicate_row_count"] == 0


def test_duplicate_detection_identifies_collisions(validator):
    """Verify primary key collisions and duplicate rows are identified."""
    defect_data = _load_json(FIXTURES_DIR / "cmo_defect_duplicate_records.json")
    result = validator.validate_duplicates(defect_data["records"])

    assert result["status"] == "FAIL"
    assert result["duplicate_campaign_id_count"] == 1
    assert "CMP-2026-Q4-001" in result["duplicate_campaign_ids"]
    assert result["duplicate_row_count"] == 1
    assert result["duplicate_percentage"] > 0


# ---------------------------------------------------------------------------
# Pillar 4: Missing Records & Completeness
# ---------------------------------------------------------------------------


def test_completeness_passes_on_complete_records(validator, valid_records):
    """Verify valid sample has zero missing cells across all required fields."""
    result = validator.validate_completeness_and_missing_records(valid_records)
    assert result["status"] == "PASS"
    assert result["score"] == 100.0
    assert result["missing_cells"] == 0
    assert result["violating_row_count"] == 0


def test_completeness_detects_missing_records(validator):
    """Verify null or empty fields in critical metrics are detected."""
    defect_data = _load_json(FIXTURES_DIR / "cmo_defect_missing_records.json")
    result = validator.validate_completeness_and_missing_records(defect_data["records"])

    assert result["status"] == "FAIL"
    assert result["score"] < 100.0
    assert result["missing_cells"] > 0
    assert "spend_usd" in result["missing_by_field"]
    assert "conversions" in result["missing_by_field"]
    assert "campaign_id" in result["missing_by_field"]


# ---------------------------------------------------------------------------
# Pillar 5: Metric Integrity Boundaries
# ---------------------------------------------------------------------------


def test_integrity_boundaries_pass_on_valid_sample(validator, valid_records):
    """Verify impressions >= clicks >= conversions >= 0 and positive spend."""
    result = validator.validate_integrity_boundaries(valid_records)
    assert result["status"] == "PASS"
    assert result["score"] == 100.0
    assert result["violation_count"] == 0


def test_integrity_boundaries_detect_violations(validator):
    """Verify impossible funnel numbers and negative spend are trapped."""
    defect_data = _load_json(FIXTURES_DIR / "cmo_defect_integrity_violations.json")
    result = validator.validate_integrity_boundaries(defect_data["records"])

    assert result["status"] == "FAIL"
    assert result["violation_count"] >= 3

    errors = [v["error"] for v in result["violations"]]
    assert any("clicks" in e and "exceed impressions" in e for e in errors)
    assert any("conversions" in e and "exceed clicks" in e for e in errors)
    assert any("spend_usd" in e and "negative" in e for e in errors)


# ---------------------------------------------------------------------------
# Unified 5-Pillar CMO Validation Report
# ---------------------------------------------------------------------------


def test_unified_validation_report_certified_on_clean_data(validator, valid_records):
    """Verify full validation pipeline certifies clean CMO data as TRUSTED."""
    metadata = _load_json(ROOT / "datasets" / "cmo" / "cmo_metadata.json")
    report = validator.validate_cmo_data_slice(valid_records, metadata=metadata)

    assert report["composite_integrity_score"] == 100.0
    assert report["classification"] == "TRUSTED"
    assert report["certification_status"] == "CERTIFIED"
    assert report["risk_flags"] == []
    assert report["validator"] == "Hariom Upadhyay (MASTERDB Data Integrity Lead)"
    assert report["total_records_analyzed"] == 10
    assert len(report["recommendations"]) == 0


def test_unified_validation_report_rejects_defective_data(validator):
    """Verify pipeline rejects defective data and issues remediation recommendations."""
    defect_records = _load_json(FIXTURES_DIR / "cmo_defect_integrity_violations.json")["records"]
    report = validator.validate_cmo_data_slice(defect_records)

    assert report["composite_integrity_score"] < 80.0
    assert report["classification"] == "REJECTED"
    assert report["certification_status"] == "REJECTED"
    assert "METRIC_INTEGRITY_BOUNDARY_VIOLATION" in report["risk_flags"]
    assert len(report["recommendations"]) > 0


# ---------------------------------------------------------------------------
# Pillar 6: Governed Capability Retrieval Correctness
# ---------------------------------------------------------------------------


def test_cmo_capability_retrieval_flow_end_to_end(valid_records, validator):
    """Verify governed data retrieval, filtering, and cryptographic digest generation."""
    # 1. Unfiltered retrieval
    res_all = validator.validate_retrieval_correctness(valid_records, {})
    assert res_all["status"] == "SUCCESS"
    assert res_all["returned_record_count"] == 10
    assert "content_digest_sha256" in res_all

    # 2. Filter by channel = 'search'
    res_search = validator.validate_retrieval_correctness(valid_records, {"channel": "search"})
    assert res_search["status"] == "SUCCESS"
    assert res_search["returned_record_count"] == 3
    assert all(r["channel"] == "search" for r in res_search["records"])

    # 3. Filter by min_roas >= 5.0
    res_roas = validator.validate_retrieval_correctness(valid_records, {"min_roas": 5.0})
    assert res_roas["status"] == "SUCCESS"
    assert res_roas["returned_record_count"] >= 3
    assert all(r["roas"] >= 5.0 for r in res_roas["records"])

    # 4. Limit pagination
    res_limit = validator.validate_retrieval_correctness(valid_records, {"limit": 2})
    assert res_limit["status"] == "SUCCESS"
    assert res_limit["returned_record_count"] == 2


def test_capability_registry_cmo_contract_and_governance():
    """Verify capability registration, contract resolution, and default-deny enforcement."""
    cap = main.capability_registry_service.get_capability("cap-cmo-marketing-intelligence")
    assert cap is not None
    assert cap.domain == "marketing"
    assert cap.purpose == "marketing_intelligence"

    contract = main.capability_registry_service.get_contract("cap-cmo-marketing-intelligence")
    assert contract.capability_id == "cap-cmo-marketing-intelligence"
    assert contract.dataset_id == "ds-cmo-marketing-001"

    # Default-deny when unauthenticated or without grant
    from models import CapabilityRetrieveRequest
    from services.capability_registry_service import CapabilityAccessDeniedError
    with pytest.raises(CapabilityAccessDeniedError) as exc_info:
        main.capability_registry_service.retrieve(
            actor="UNAUTHORIZED",
            roles=["viewer"],
            capability_id="cap-cmo-marketing-intelligence",
            retrieve_req=CapabilityRetrieveRequest(application_id="UNAUTHORIZED"),
        )
    assert "Valid access grant required" in str(exc_info.value)
