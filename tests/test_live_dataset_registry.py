from fastapi.testclient import TestClient

import main
from auth.models import AuthIdentity
from services.aircraft_observation_service import AircraftObservationService
from services.ais_observation_service import AISObservationService
from services.artifact_store import ArtifactStore
from services.earthquake_observation_service import EarthquakeObservationService
from services.fire_observation_service import FireObservationService
from services.traffic_observation_service import TrafficObservationService
from services.weather_observation_service import WeatherObservationService
from services.cyclone_observation_service import CycloneObservationService
from services.source_registry_service import SourceRegistryService


def test_live_feed_registry_does_not_verify_empty_observation_stores(tmp_path):
    old_services = (main.earthquake_observation_service, main.ais_observation_service, main.aircraft_observation_service, main.fire_observation_service, main.traffic_observation_service, main.weather_observation_service, main.cyclone_observation_service)
    old_traffic_state = (main.traffic_last_verified_at, main.traffic_verified_tiles, main.traffic_last_fetch_error)
    old_observation_feed_state = {key: dict(value) for key, value in main.observation_feed_state.items()}
    main.earthquake_observation_service = EarthquakeObservationService(ArtifactStore(str(tmp_path / "earthquakes")))
    main.ais_observation_service = AISObservationService(ArtifactStore(str(tmp_path / "ais")))
    main.aircraft_observation_service = AircraftObservationService(ArtifactStore(str(tmp_path / "aircraft")))
    main.fire_observation_service = FireObservationService(ArtifactStore(str(tmp_path / "fires")))
    main.traffic_observation_service = TrafficObservationService(ArtifactStore(str(tmp_path / "traffic")))
    main.weather_observation_service = WeatherObservationService(ArtifactStore(str(tmp_path / "weather")))
    main.cyclone_observation_service = CycloneObservationService(ArtifactStore(str(tmp_path / "cyclones")))
    main.traffic_last_verified_at, main.traffic_verified_tiles, main.traffic_last_fetch_error = None, [], False
    main.observation_feed_state = {
        "usgs": {"status": "PENDING", "last_verified_at_utc": None},
        "aisstream": {"status": "PENDING", "last_verified_at_utc": None},
        "adsb_military": {"status": "PENDING", "last_verified_at_utc": None},
    }
    main.app.dependency_overrides[main.get_identity] = lambda: AuthIdentity(actor="test", roles=["viewer"])
    try:
        client = TestClient(main.app)
        response = client.get("/live-datasets")
        assert response.status_code == 200
        payload = response.json()
        assert payload["count"] == 24
        assert {item["dataset_id"] for item in payload["datasets"]} == {
            "gods_eye_view_natural_earth_regions", "gods_eye_view_natural_earth_marine",
            "gods_eye_view_openfreemap_vector_basemap",
            "gods_eye_view_world_3d_terrain",
            "gods_eye_view_world_satellite_imagery",
            "google_cesium_photorealistic_3d_tiles",
            "gods_eye_view_bhote_koshi_flood",
            "gods_eye_view_dams",
            "ds-gev-seismic-events", "aisstream_vessel_positions", "adsb_military_aircraft_observations", "nasa_firms_active_fires", "tomtom_traffic_flow_segments",
            "gev_gfs_wind_forecasts", "gev_ecmwf_wind_forecasts", "open_meteo_current_surface_weather",
            "noaa_nowcoast_conus_base_reflectivity_radar",
            "noaa_nowcoast_global_satellite_cloud_imagery", "noaa_nowcoast_goes_regional_satellite_cloud_imagery",
            "noaa_nowcoast_lightning_strike_density_imagery",
            "noaa_nhc_current_tropical_cyclones", "noaa_nhc_cyclone_forecast_points", "noaa_nhc_cyclone_tracks", "noaa_nhc_cyclone_forecast_cones",
        }
        terrain = next(item for item in payload["datasets"] if item["dataset_id"] == "gods_eye_view_world_3d_terrain")
        assert terrain["data_mode"] == "EXTERNAL_GEOPATIAL_TERRAIN_SERVICE"
        assert terrain["record_count"] == 0
        assert terrain["manifest_endpoint"] == "/geospatial/terrain/manifest"
        assert terrain["verification_endpoint"] == "/geospatial/terrain/verify"
        for dataset_id in ("ds-gev-seismic-events", "aisstream_vessel_positions", "adsb_military_aircraft_observations"):
            item = next(row for row in payload["datasets"] if row["dataset_id"] == dataset_id)
            assert item["status"] == "PENDING"
            assert item["record_count"] == 0
        vector_basemap = next(item for item in payload["datasets"] if item["dataset_id"] == "gods_eye_view_openfreemap_vector_basemap")
        assert vector_basemap["data_mode"] == "EXTERNAL_GEOPATIAL_VECTOR_TILE_SERVICE"
        assert vector_basemap["record_count"] == 0
        assert vector_basemap["manifest_endpoint"] == "/geospatial/vector-basemap/manifest"
        assert vector_basemap["verification_endpoint"] == "/geospatial/vector-basemap/verify"
        page = client.get("/live-datasets/registry")
        assert page.status_code == 200
        assert "/live-datasets" in page.text
        assert "Attribution:" in page.text
        assert "Verify service" in page.text
        assert "Status and data mode distinguish live feeds from static snapshots" in page.text
    finally:
        main.app.dependency_overrides.pop(main.get_identity, None)
        (main.earthquake_observation_service, main.ais_observation_service, main.aircraft_observation_service, main.fire_observation_service, main.traffic_observation_service, main.weather_observation_service, main.cyclone_observation_service) = old_services
        main.traffic_last_verified_at, main.traffic_verified_tiles, main.traffic_last_fetch_error = old_traffic_state
        main.observation_feed_state = old_observation_feed_state


def test_legacy_live_status_without_readback_is_demoted_to_pending(tmp_path):
    old_registry = main.source_registry_service
    main.source_registry_service = SourceRegistryService(store_dir=str(tmp_path / "registry"))
    service = EarthquakeObservationService(ArtifactStore(str(tmp_path / "empty-earthquakes")))
    main.source_registry_service.mark_fetch_status(
        "src-gev-usgs-seismic", "LIVE_VERIFIED", {"credential_values_stored": False},
    )
    try:
        restored = main._restore_observation_feed_state("usgs", service)
        record = main.source_registry_service.get_source("src-gev-usgs-seismic")
        assert restored["status"] == "PENDING"
        assert record.provenance_reference["last_fetch_status"] == "PENDING"
        assert record.provenance_reference["last_verification"]["stored_dataset_records"] == 0
    finally:
        main.source_registry_service = old_registry
