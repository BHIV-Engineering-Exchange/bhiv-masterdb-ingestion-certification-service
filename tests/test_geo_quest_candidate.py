import json
from pathlib import Path
import shutil

import pytest

from geo_quest_candidate.service import (
    CAPABILITY_ID,
    CandidateNotFoundError,
    CandidateRegistrationError,
    CandidateRetrieveRequest,
    GeoQuestCandidateService,
)


def test_validated_geo_quest_candidate_registration_and_filtered_reuse(tmp_path):
    service = GeoQuestCandidateService(store_dir=str(tmp_path / "candidate-store"))

    registration = service.register_candidate(actor="candidate-reviewer")
    assert registration["capability_id"] == CAPABILITY_ID
    assert registration["registration_status"] == "PENDING_AUTHORIZATION"
    assert registration["canonical"] is False
    assert registration["discoverable"] is False
    assert registration["record_count"] == 19

    details = service.get_candidate(CAPABILITY_ID)
    assert details["source"]["source_name"] == "adsb.lol"
    assert details["dataset"]["registration_status"] == "PENDING"
    assert details["schema"]["field_count"] == 20
    assert details["quality_report"]["overall_status"] == "PASS"

    response = service.retrieve(
        CAPABILITY_ID,
        CandidateRetrieveRequest(filter_hex_id=" abe5a2 "),
    )
    assert response["query_metadata"]["matched_record_count"] == 1
    assert response["records"][0]["aircraft_hex_id"] == "ABE5A2"
    assert response["records"][0]["callsign"] == "FDX8"
    assert response["records"][0]["provenance"]["source_system"] == "adsb.lol"
    assert response["provenance"]["licence"]["licence_name"].startswith("Open Data Commons")


def test_registration_rejects_missing_candidate_artifacts(tmp_path):
    project_root = Path(__file__).resolve().parents[1] / "MASTERDB-GEO-QUEST-01"
    service = GeoQuestCandidateService(
        store_dir=str(tmp_path / "candidate-store"),
        project_root=project_root / "missing",
    )

    with pytest.raises(CandidateRegistrationError, match="Unable to load candidate artifact"):
        service.register_candidate(actor="candidate-reviewer")


def test_registration_rejects_cleaned_records_that_do_not_match_pipeline(tmp_path):
    source_root = Path(__file__).resolve().parents[1] / "MASTERDB-GEO-QUEST-01"
    project_root = tmp_path / "candidate-project"
    shutil.copytree(source_root, project_root)
    cleaned_path = project_root / "cleaned" / "aircraft_cleaned.json"
    cleaned = json.loads(cleaned_path.read_text(encoding="utf-8"))
    cleaned["records"][0]["callsign"] = "UNVERIFIED"
    cleaned_path.write_text(json.dumps(cleaned), encoding="utf-8")
    service = GeoQuestCandidateService(
        store_dir=str(tmp_path / "candidate-store"),
        project_root=project_root,
    )

    with pytest.raises(CandidateRegistrationError, match="do not match"):
        service.register_candidate(actor="candidate-reviewer")


def test_retrieval_detects_candidate_record_tampering(tmp_path):
    service = GeoQuestCandidateService(store_dir=str(tmp_path / "candidate-store"))
    service.register_candidate(actor="candidate-reviewer")
    bundle = service.store.load(CAPABILITY_ID)
    bundle["records"][0]["callsign"] = "ALTERED"
    service.store.save(CAPABILITY_ID, bundle)

    with pytest.raises(CandidateRegistrationError, match="integrity check"):
        service.retrieve(CAPABILITY_ID, CandidateRetrieveRequest())


def test_candidate_registry_does_not_resolve_arbitrary_ids(tmp_path):
    service = GeoQuestCandidateService(store_dir=str(tmp_path / "candidate-store"))

    with pytest.raises(CandidateNotFoundError):
        service.get_candidate("../../registry_store/unknown")
