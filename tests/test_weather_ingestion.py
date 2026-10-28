import struct

import pytest
from fastapi.testclient import TestClient

import main
from auth.models import AuthIdentity
from integrations import weather_connector
from services.artifact_store import ArtifactStore
from services.weather_observation_service import WeatherObservationService


def test_open_meteo_normalization_and_timestamp_validation():
    payload = {
        "latitude": 37.8, "longitude": -122.4, "elevation": 12,
        "current_units": {"wind_speed_10m": "m/s", "pressure_msl": "hPa"},
        "current": {"time": "2026-10-24T12:00", "temperature_2m": 18, "pressure_msl": 1013,
                    "wind_speed_10m": 3.5, "wind_direction_10m": 225, "relative_humidity_2m": 66},
    }
    row = weather_connector.normalize_open_meteo(payload, {"latitude": 37.8, "longitude": -122.4})
    assert row["record_type"] == "CURRENT_CONDITIONS" and row["is_forecast"] is False
    assert row["observed_at_utc"].endswith("+00:00")
    assert row["wind_speed_10m_mps"] == 3.5
    payload["current"]["time"] = "not-a-time"
    with pytest.raises(ValueError):
        weather_connector.normalize_open_meteo(payload, {"latitude": 37.8, "longitude": -122.4})


def test_wind_grid_sampling_and_validation():
    grid = {"nx": 4, "ny": 3, "dx": 90, "dy": 90}
    body = struct.pack("<" + "f" * 36, *([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] + [13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24] + [25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36]))
    assert weather_connector._sample_grid(body, grid, 0, 90, scalar=True) == (6.0, 18.0, 30.0)
    with pytest.raises(ValueError):
        weather_connector.validate_location({"latitude": 91, "longitude": 0})


def test_weather_storage_deduplicates_by_place_and_observation_time(tmp_path):
    service = WeatherObservationService(ArtifactStore(str(tmp_path / "weather")))
    row = {"source": "Open-Meteo", "record_type": "CURRENT_CONDITIONS", "is_forecast": False,
           "latitude": 10.0, "longitude": 20.0, "observed_at_utc": "2026-10-24T12:00:00+00:00", "temperature_2m_c": 28.0}
    feed = {"source": "Open-Meteo", "observations": [row]}
    first = service.ingest(feed, forecast=False)
    second = service.ingest(feed, forecast=False)
    assert first["inserted"] == 1 and second["updated"] == 1
    stored = service.get(first["record_ids"][0])
    assert stored["dataset_id"] == service.CURRENT_DATASET
    assert stored["is_forecast"] is False


def test_weather_routes_require_readback_before_live_verified(monkeypatch, tmp_path):
    old_service, old_state, old_registry = main.weather_observation_service, main.weather_source_state, main.source_registry_service
    main.weather_observation_service = WeatherObservationService(ArtifactStore(str(tmp_path / "route-weather")))
    main.weather_source_state = {
        "src-gev-gfs-wind": {"last_verified_at_utc": None, "last_fetch_status": "CONFIGURED", "verified_coordinates": []},
        "src-gev-ecmwf-wind": {"last_verified_at_utc": None, "last_fetch_status": "CONFIGURED", "verified_coordinates": []},
        "src-open-meteo-current-weather": {"last_verified_at_utc": None, "last_fetch_status": "CONFIGURED", "verified_coordinates": []},
    }

    class Registry:
        calls = []
        def mark_validated(self, *args): self.calls.append(("validated", args))
        def mark_fetch_status(self, *args): self.calls.append(("fetch", args))

    registry = Registry()
    main.source_registry_service = registry
    when = "2026-10-24T12:00:00+00:00"
    monkeypatch.setattr(main, "fetch_wind_forecasts", lambda model, locations: {"source": "GEV", "model": model.upper(), "cycle": {"validIso": when}, "observations": [{"source": "GEV", "model": model.upper(), "record_type": "FORECAST", "is_forecast": True, "latitude": 10.0, "longitude": 20.0, "run_time_utc": when, "forecast_valid_at_utc": when, "wind_u_mps": 1.0, "wind_v_mps": 2.0, "wind_speed_mps": 2.236, "wind_direction_degrees": 206.5}]})
    monkeypatch.setattr(main, "fetch_open_meteo_current", lambda locations: {"source": "Open-Meteo", "observations": [{"source": "Open-Meteo", "record_type": "CURRENT_CONDITIONS", "is_forecast": False, "latitude": 10.0, "longitude": 20.0, "observed_at_utc": when, "temperature_2m_c": 29.0}]})
    main.app.dependency_overrides[main.get_identity] = lambda: AuthIdentity(actor="weather-test", roles=["viewer"])
    try:
        client = TestClient(main.app)
        wind = client.post("/weather/wind/gfs/ingest", json={"locations": [{"latitude": 10, "longitude": 20}]})
        current = client.post("/weather/open-meteo/ingest", json={"locations": [{"latitude": 10, "longitude": 20}]})
        assert wind.status_code == current.status_code == 200
        assert wind.json()["readback_count"] == current.json()["readback_count"] == 1
        assert main.weather_source_state["src-gev-gfs-wind"]["last_fetch_status"] == "LIVE_VERIFIED"
        assert main.weather_source_state["src-open-meteo-current-weather"]["last_fetch_status"] == "LIVE_VERIFIED"
        assert client.get("/weather/wind/forecasts?model=gfs").json()["count"] == 1
        assert client.get("/weather/open-meteo/current").json()["count"] == 1
        registry_payload = client.get("/live-datasets").json()
        assert {item["dataset_id"] for item in registry_payload["datasets"]} >= {
            "gev_gfs_wind_forecasts", "gev_ecmwf_wind_forecasts", "open_meteo_current_surface_weather",
        }
        assert any(call[0] == "validated" for call in registry.calls)
    finally:
        main.app.dependency_overrides.pop(main.get_identity, None)
        main.weather_observation_service, main.weather_source_state, main.source_registry_service = old_service, old_state, old_registry
