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
from services.source_registry_service import SourceRegistryService


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
    previous_registry = main.source_registry_service
    previous_feed_state = main.observation_feed_state["usgs"]
    main.earthquake_observation_service = EarthquakeObservationService(ArtifactStore(str(tmp_path)))
    main.source_registry_service = SourceRegistryService(store_dir=str(tmp_path / "registry"))
    main.observation_feed_state["usgs"] = {"status": "PENDING", "last_verified_at_utc": None}
    monkeypatch.setattr(main, "fetch_earthquakes", lambda: {"source": "USGS", "observations": [observation()]})
    main.app.dependency_overrides[main.get_identity] = lambda: AuthIdentity(actor="test", roles=["operator"])
    try:
        client = TestClient(main.app)
        response = client.post("/earthquakes/usgs/ingest")
        assert response.status_code == 200
        assert response.json()["inserted"] == 1
        assert response.json()["status"] == "LIVE_VERIFIED"
        assert response.json()["readback_records"] == 1
        assert response.json()["registry_readback"] is True
        listed = client.get("/earthquakes/usgs/observations")
        assert listed.status_code == 200
        assert listed.json()["observations"][0]["event_id"] == "us-test-1"
        source = main.source_registry_service.get_source("src-gev-usgs-seismic")
        assert source.provenance_reference["last_fetch_status"] == "LIVE_VERIFIED"
        assert source.provenance_reference["last_verification"]["readback_records"] == 1
        listed_dataset = next(
            row for row in client.get("/live-datasets").json()["datasets"]
            if row["dataset_id"] == "ds-gev-seismic-events"
        )
        assert listed_dataset["status"] == "LIVE_VERIFIED"
        assert listed_dataset["record_count"] == 1
        assert client.get("/earthquakes/map").status_code == 200
    finally:
        main.app.dependency_overrides.pop(main.get_identity, None)
        main.earthquake_observation_service = previous
        main.source_registry_service = previous_registry
        main.observation_feed_state["usgs"] = previous_feed_state


def test_empty_usgs_feed_stays_pending(monkeypatch, tmp_path):
    previous = (main.earthquake_observation_service, main.source_registry_service,
                main.observation_feed_state["usgs"])
    main.earthquake_observation_service = EarthquakeObservationService(ArtifactStore(str(tmp_path / "earthquakes")))
    main.source_registry_service = SourceRegistryService(store_dir=str(tmp_path / "registry"))
    main.observation_feed_state["usgs"] = {"status": "PENDING", "last_verified_at_utc": None}
    monkeypatch.setattr(main, "fetch_earthquakes", lambda: {"source": "USGS", "observations": []})
    main.app.dependency_overrides[main.get_identity] = lambda: AuthIdentity(actor="test", roles=["operator"])
    try:
        response = TestClient(main.app).post("/earthquakes/usgs/ingest")
        assert response.status_code == 200
        assert response.json()["status"] == "PENDING"
        assert response.json()["readback_records"] == 0
        source = main.source_registry_service.get_source("src-gev-usgs-seismic")
        assert source.provenance_reference["last_fetch_status"] == "PENDING"
    finally:
        main.app.dependency_overrides.pop(main.get_identity, None)
        (main.earthquake_observation_service, main.source_registry_service,
         main.observation_feed_state["usgs"]) = previous
