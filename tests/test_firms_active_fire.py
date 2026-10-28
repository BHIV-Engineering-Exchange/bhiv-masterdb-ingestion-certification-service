from fastapi.testclient import TestClient

import main
from auth.models import AuthIdentity
from integrations.firms_active_fire_connector import normalize_fire
from services.artifact_store import ArtifactStore
from services.fire_observation_service import FireObservationService


def test_normalize_firms_csv_fields_and_skip_invalid_rows():
    row = {"latitude": "34.2", "longitude": "-118.4", "acq_date": "2026-10-24", "acq_time": "0812",
           "satellite": "N", "confidence": "n", "bright_ti4": "321.4", "frp": "8.2", "daynight": "D"}
    normalized = normalize_fire(row, "VIIRS_NOAA20_NRT")
    assert normalized["observation_time_utc"] == "2026-10-24T08:12:00+00:00"
    assert normalized["satellite"] == "N"
    assert normalized["confidence"] == "n"
    assert normalized["brightness"] == 321.4
    assert normalized["source_id"].startswith("firms:VIIRS_NOAA20_NRT:")
    assert normalize_fire({**row, "latitude": "91"}, "VIIRS_NOAA20_NRT") is None
    assert normalize_fire({**row, "acq_time": "2500"}, "VIIRS_NOAA20_NRT") is None


def test_firms_service_deduplicates_source_and_observation_time_and_skips_invalid(tmp_path):
    service = FireObservationService(ArtifactStore(str(tmp_path)))
    fire = {"source_id": "firms:test", "source": "NASA FIRMS", "latitude": 12.3, "longitude": 45.6,
            "observation_time_utc": "2026-10-24T08:12:00+00:00", "satellite": "N", "confidence": "h", "brightness": 300}
    first = service.ingest({"source": "NASA FIRMS", "observations": [fire, {**fire, "latitude": 100}]})
    second = service.ingest({"source": "NASA FIRMS", "observations": [fire]})
    assert first["inserted"] == 1 and first["skipped"] == 1
    assert second["updated"] == 1
    assert len(service.list()) == 1


def test_firms_endpoints_readback_and_live_registry(tmp_path, monkeypatch):
    old_service, old_verified = main.fire_observation_service, main.firms_last_verified_at
    main.fire_observation_service = FireObservationService(ArtifactStore(str(tmp_path)))
    main.firms_last_verified_at = None
    monkeypatch.setenv("FIRMS_MAP_KEY", "configured")
    monkeypatch.setattr(main, "fetch_active_fires", lambda: {"source": "NASA FIRMS", "record_count": 1,
        "observations": [{"source_id": "firms:sample", "source": "NASA FIRMS", "latitude": 12.3, "longitude": 45.6,
                          "observation_time_utc": "2026-10-24T08:12:00+00:00", "satellite": "N", "confidence": "h", "brightness": 300}]})
    main.app.dependency_overrides[main.get_identity] = lambda: AuthIdentity(actor="test", roles=["viewer"])
    try:
        client = TestClient(main.app)
        response = client.post("/wildfires/firms/ingest")
        assert response.status_code == 200
        assert response.json()["inserted"] == 1
        readback = client.get("/wildfires/firms/observations").json()
        assert readback["count"] == 1
        registry = client.get("/live-datasets").json()
        entry = next(item for item in registry["datasets"] if item["dataset_id"] == "nasa_firms_active_fires")
        assert entry["status"] == "LIVE_VERIFIED"
        assert entry["record_count"] == 1
        assert client.get("/live-datasets/registry").status_code == 200
    finally:
        main.app.dependency_overrides.pop(main.get_identity, None)
        main.fire_observation_service, main.firms_last_verified_at = old_service, old_verified
