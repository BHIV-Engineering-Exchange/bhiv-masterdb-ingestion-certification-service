from fastapi.testclient import TestClient

import main
from main import app
from geo_quest_candidate.service import GeoQuestCandidateService

client = TestClient(app)


def _token(actor, roles):
    response = client.post("/auth/token", json={"actor": actor, "roles": roles})
    assert response.status_code == 200
    return response.json()["access_token"]


def test_geo_quest_registration_and_end_to_end_retrieval(tmp_path, monkeypatch):
    monkeypatch.setattr(
        main,
        "geo_quest_candidate_service",
        GeoQuestCandidateService(store_dir=str(tmp_path / "candidate-store")),
    )
    admin_token = _token("admin", ["bhiv-admin"])
    headers = {"Authorization": f"Bearer {admin_token}"}

    registered = client.post(
        "/geo-quest/candidates/gev.aircraft_tracking/register",
        headers=headers,
    )
    assert registered.status_code == 200
    body = registered.json()
    assert body["registration_status"] == "PENDING_AUTHORIZATION"
    assert body["canonical"] is False
    assert body["discoverable"] is False
    assert body["mdu_schema_contract"]["dataset_id"] == "BHIV-GEO-QUEST-01-AIRCRAFT"
    assert "compatible" in body["mdu_schema_compatibility"]

    details = client.get("/geo-quest/candidates/gev.aircraft_tracking", headers=headers)
    assert details.status_code == 200
    assert details.json()["source"]["source_name"] == "adsb.lol"
    assert details.json()["schema"]["field_count"] == 20

    retrieved = client.post(
        "/geo-quest/candidates/gev.aircraft_tracking/retrieve",
        json={"filter_callsign": "FDX"},
        headers=headers,
    )
    assert retrieved.status_code == 200
    response = retrieved.json()
    assert response["capability"]["discoverable"] is False
    assert response["query_metadata"]["matched_record_count"] == 1
    assert response["records"][0]["callsign"] == "FDX8"

    capabilities = client.get("/capabilities?search=gev", headers=headers)
    assert capabilities.status_code == 200
    assert all(item["capability_id"] != "gev.aircraft_tracking" for item in capabilities.json())


def test_geo_quest_candidate_write_and_retrieval_require_admin():
    viewer_token = _token("candidate-viewer", ["ecosystem-reader"])
    headers = {"Authorization": f"Bearer {viewer_token}"}

    registration = client.post(
        "/geo-quest/candidates/gev.aircraft_tracking/register",
        headers=headers,
    )
    assert registration.status_code == 403

    retrieval = client.post(
        "/geo-quest/candidates/gev.aircraft_tracking/retrieve",
        json={},
        headers=headers,
    )
    assert retrieval.status_code == 403
