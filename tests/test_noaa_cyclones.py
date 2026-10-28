from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main
from auth.models import AuthIdentity
from integrations.noaa_cyclone_connector import (
    CycloneUpstreamError, CycloneValidationError, normalize_cyclone_response,
)
from services.artifact_store import ArtifactStore
from services.cyclone_observation_service import CycloneObservationService


NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
ISSUED = "2026-10-24T11:00:00.000Z"


def upstream_payload():
    return {
        "schemaVersion": 1, "source": "NOAA NHC / CPHC", "attribution": "NOAA/NWS National Hurricane Center",
        "coverage": "Atlantic and eastern/central North Pacific; not worldwide cyclone coverage.",
        "fetchedAt": NOW.timestamp() * 1000, "stale": False, "unavailable": False,
        "storms": [{
            "id": "al012026", "name": "Example", "classification": "Tropical Storm", "basin": "AL",
            "position": {"longitude": -70.0, "latitude": 20.0}, "positionAt": ISSUED,
            "advisoryNumber": "10A", "issuedAt": ISSUED, "windKt": 45, "pressureHpa": None,
            "movement": {"directionDegrees": 300, "speedKt": 8}, "advisoryUrl": None,
            "outlookUrl": "https://www.nhc.noaa.gov/gtwo.php?basin=atlc&fdays=7",
            "geometryStatus": "current", "geometryAdvisoryNumber": "10A",
            "forecastPoints": [
                {"position": {"longitude": -70.0, "latitude": 20.0}, "tauHours": 0, "windKt": 45, "gustKt": None},
                {"position": {"longitude": -68.0, "latitude": 21.0}, "tauHours": 12, "windKt": None, "gustKt": 60},
            ],
            "track": {"type": "LineString", "coordinates": [[-70.0, 20.0], [-68.0, 21.0]]},
            "cone": {"type": "Polygon", "coordinates": [[[-71, 19], [-67, 19], [-67, 22], [-71, 19]]]},
        }],
    }


def normalized_feed():
    return normalize_cyclone_response(upstream_payload(), now=NOW)


def test_cyclone_normalization_preserves_optional_fields_and_gis():
    feed = normalized_feed()
    storm = feed["storms"][0]
    assert storm["source_id"] == "al012026"
    assert storm["position"] == {"longitude": -70.0, "latitude": 20.0}
    assert storm["position_at_utc"] == ISSUED
    assert storm["pressure_hpa"] is None
    assert storm["forecast_points"][1]["wind_speed_kt"] is None
    assert storm["track"]["type"] == "LineString"
    assert storm["cone"]["type"] == "Polygon"


def test_cyclone_validation_rejects_bad_time_and_geometry():
    payload = upstream_payload()
    payload["storms"][0]["positionAt"] = "not-a-timestamp"
    with pytest.raises(CycloneValidationError):
        normalize_cyclone_response(payload, now=NOW)
    payload = upstream_payload()
    payload["storms"][0]["cone"]["coordinates"][0][-1] = [-70, 20]
    with pytest.raises(CycloneValidationError):
        normalize_cyclone_response(payload, now=NOW)


def test_cyclone_storage_deduplicates_and_exposes_only_latest_snapshot(tmp_path):
    service = CycloneObservationService(ArtifactStore(str(tmp_path / "cyclone-store")))
    feed = normalized_feed()
    first = service.ingest(feed)
    second = service.ingest(feed)
    assert first["storms"]["inserted"] == 1 and first["tracks"]["inserted"] == 1
    assert second["storms"]["updated"] == 1 and second["cones"]["updated"] == 1
    assert len(service.list("noaa_nhc_current_tropical_cyclones")) == 1
    assert len(service.list("noaa_nhc_cyclone_forecast_points")) == 2
    empty = {**feed, "fetched_at_utc": "2026-10-24T11:30:00+00:00", "storms": []}
    service.ingest(empty)
    assert service.list("noaa_nhc_current_tropical_cyclones") == []
    assert service.list("noaa_nhc_cyclone_tracks") == []


def test_cyclone_api_storage_readback_and_registry(monkeypatch, tmp_path):
    old_service, old_registry, old_state = main.cyclone_observation_service, main.source_registry_service, main.cyclone_source_state
    main.cyclone_observation_service = CycloneObservationService(ArtifactStore(str(tmp_path / "api-cyclone-store")))
    main.cyclone_source_state = {kind: {"last_verified_at_utc": None, "last_fetch_status": "CONFIGURED", "last_metadata": {}} for kind in ("storms", "points", "tracks", "cones")}

    class Registry:
        def __init__(self): self.rows = {}
        def mark_validated(self, source_id, at, metadata):
            row = self.rows.setdefault(source_id, {"last_validation": "NOT VERIFIED", "provenance_reference": {}})
            row["last_validation"] = at
            row["provenance_reference"].update(metadata)
        def mark_fetch_status(self, source_id, status, metadata):
            row = self.rows.setdefault(source_id, {"last_validation": "NOT VERIFIED", "provenance_reference": {}})
            row["provenance_reference"].update(metadata)
            row["provenance_reference"]["last_fetch_status"] = status
        def get_source(self, source_id):
            row = self.rows[source_id]
            return SimpleNamespace(last_validation=row["last_validation"], provenance_reference=row["provenance_reference"])

    registry = Registry()
    main.source_registry_service = registry
    monkeypatch.setattr(main, "fetch_current_cyclones", normalized_feed)
    for name in ("earthquake_observation_service", "ais_observation_service", "aircraft_observation_service", "fire_observation_service", "traffic_observation_service", "weather_observation_service"):
        monkeypatch.setattr(getattr(main, name), "list", lambda *args, **kwargs: [])
    main.app.dependency_overrides[main.get_identity] = lambda: AuthIdentity(actor="cyclone-test", roles=["viewer"])
    try:
        client = TestClient(main.app)
        ingest = client.post("/cyclones/nhc/ingest")
        assert ingest.status_code == 200
        result = ingest.json()
        assert result["product_statuses"] == {"storms": "LIVE_VERIFIED", "points": "LIVE_VERIFIED", "tracks": "LIVE_VERIFIED", "cones": "LIVE_VERIFIED"}
        assert result["readback_counts"] == {"storms": 1, "points": 2, "tracks": 1, "cones": 1}
        assert client.get("/cyclones/nhc/storms").json()["count"] == 1
        assert client.get("/cyclones/nhc/forecast-points").json()["count"] == 2
        assert client.get("/cyclones/nhc/tracks").json()["features"][0]["geometry"]["type"] == "LineString"
        assert client.get("/cyclones/nhc/cones").json()["features"][0]["geometry"]["type"] == "Polygon"
        registry_rows = client.get("/live-datasets").json()["datasets"]
        status_row = next(row for row in registry_rows if row["dataset_id"] == "noaa_nhc_current_tropical_cyclones")
        assert status_row["status"] == "LIVE_VERIFIED" and status_row["record_count"] == 1
        assert registry.rows["src-gev-noaa-nhc-cyclone-tracks"]["provenance_reference"]["last_fetch_status"] == "LIVE_VERIFIED"
    finally:
        main.app.dependency_overrides.pop(main.get_identity, None)
        main.cyclone_observation_service, main.source_registry_service, main.cyclone_source_state = old_service, old_registry, old_state


def test_cyclone_upstream_error_does_not_mark_live(monkeypatch):
    old_state, old_registry = main.cyclone_source_state, main.source_registry_service
    main.cyclone_source_state = {kind: {"last_verified_at_utc": None, "last_fetch_status": "CONFIGURED", "last_metadata": {}} for kind in ("storms", "points", "tracks", "cones")}

    class Registry:
        statuses = {}
        def mark_fetch_status(self, source_id, status, metadata): self.statuses[source_id] = status

    registry = Registry()
    main.source_registry_service = registry
    def fail():
        raise CycloneUpstreamError("upstream unavailable")
    monkeypatch.setattr(main, "fetch_current_cyclones", fail)
    main.app.dependency_overrides[main.get_identity] = lambda: AuthIdentity(actor="cyclone-error-test", roles=["viewer"])
    try:
        response = TestClient(main.app).post("/cyclones/nhc/ingest")
        assert response.status_code == 502
        assert main.cyclone_source_state["storms"]["last_fetch_status"] == "UNAVAILABLE"
        assert all(value == "UNAVAILABLE" for value in registry.statuses.values())
    finally:
        main.app.dependency_overrides.pop(main.get_identity, None)
        main.cyclone_source_state, main.source_registry_service = old_state, old_registry
