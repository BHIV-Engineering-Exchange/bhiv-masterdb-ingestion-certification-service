from fastapi.testclient import TestClient
import pytest

import main
from auth.models import AuthIdentity
from services.artifact_store import ArtifactStore
from services.earthquake_observation_service import (
    EarthquakeObservationService,
    EarthquakeObservationValidationError,
)
from services.sql_artifact_store import SqlArtifactStore


def observation(event_id="us-test-1", magnitude=4.2):
    return {"event_id": event_id, "source": "USGS", "place": "Test place", "magnitude": magnitude,
            "longitude": 151.2, "latitude": -33.8, "depth_km": 12.0,
            "event_time_utc": "2026-10-23T10:00:00+00:00", "source_url": "https://earthquake.usgs.gov/test"}


def test_validation_and_upsert_updates_existing_event(tmp_path):
    service = EarthquakeObservationService(ArtifactStore(str(tmp_path)))
    assert service.ingest({"source": "USGS", "observations": [observation()]})["inserted"] == 1
    result = service.ingest({"source": "USGS", "observations": [observation(magnitude=4.8)]})
    assert result["updated"] == 1
    assert len(service.list()) == 1
    assert service.get("us-test-1")["magnitude"] == 4.8


def test_validation_rejects_bad_coordinates_and_batch_is_not_partially_saved(tmp_path):
    service = EarthquakeObservationService(ArtifactStore(str(tmp_path)))
    bad = observation("bad")
    bad["latitude"] = 91
    with pytest.raises(EarthquakeObservationValidationError):
        service.ingest({"source": "USGS", "observations": [observation(), bad]})
    assert service.list() == []


def test_validation_accepts_usgs_negative_depth_values(tmp_path):
    service = EarthquakeObservationService(ArtifactStore(str(tmp_path)))
    event = observation()
    event["depth_km"] = -0.4
    assert service.ingest({"source": "USGS", "observations": [event]})["inserted"] == 1


def test_sql_store_survives_service_restart_and_updates_key(tmp_path):
    db = f"sqlite:///{tmp_path / 'earthquakes.sqlite'}"
    first = EarthquakeObservationService(SqlArtifactStore(db, "earthquakes"))
    first.ingest({"source": "USGS", "observations": [observation()]})
    restarted = EarthquakeObservationService(SqlArtifactStore(db, "earthquakes"))
    restarted.ingest({"source": "USGS", "observations": [observation(magnitude=5.1)]})
    assert len(restarted.list()) == 1
    assert restarted.get("us-test-1")["magnitude"] == 5.1


def test_api_fetches_and_returns_stored_observations(monkeypatch, tmp_path):
    previous = main.earthquake_observation_service
    main.earthquake_observation_service = EarthquakeObservationService(ArtifactStore(str(tmp_path)))
    monkeypatch.setattr(main, "fetch_earthquakes", lambda: {"source": "USGS", "observations": [observation()]})
    main.app.dependency_overrides[main.get_identity] = lambda: AuthIdentity(actor="test", roles=["operator"])
    try:
        client = TestClient(main.app)
        response = client.post("/earthquakes/usgs/ingest")
        assert response.status_code == 200
        assert response.json()["inserted"] == 1
        listed = client.get("/earthquakes/usgs/observations")
        assert listed.status_code == 200
        assert listed.json()["observations"][0]["event_id"] == "us-test-1"
        assert client.get("/earthquakes/map").status_code == 200
    finally:
        main.app.dependency_overrides.pop(main.get_identity, None)
        main.earthquake_observation_service = previous
