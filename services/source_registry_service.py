"""
Source Registry Service — Governed Ecosystem Source Records.

Owns MASTERDB Source registration, discovery, duplicate checking, write authority confirmation,
and lifecycle tracking for geospatial and generic ecosystem sources.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from models import SourceRecord, SourceRegisterRequest, SourceStatus
from services.artifact_store import ArtifactStore
from services.crypto_audit_emitter import CryptoAuditEmitter

logger = logging.getLogger("masterdb")


class SourceNotFoundError(KeyError):
    """Raised when a requested source_id does not exist."""
    pass


class SourceAlreadyExistsError(ValueError):
    """Raised when attempting to register a source that already exists."""
    pass


class SourceRegistryService:
    def __init__(
        self,
        store_dir: str = "source_store",
        audit_emitter: Optional[CryptoAuditEmitter] = None,
    ) -> None:
        self.store = ArtifactStore(reports_dir=store_dir)
        self.audit_emitter = audit_emitter or CryptoAuditEmitter()
        self._seed_default_sources_if_empty()

    def _seed_default_sources_if_empty(self) -> None:
        defaults = [
            # NOTE: Seed records below are DEMO / TEST FIXTURES for API contract demonstration.
            # They do NOT represent live production connections to real external ground stations or gateways.
            SourceRecord(
                source_id="src-marine-intel-ports",
                name="Marine Intelligence - Indian Ports & Harbours Infrastructure",
                authority="Ministry of Ports, Shipping and Waterways / Sagarmala",
                source_type="MARITIME_PORT_REGISTRY",
                licence="PUBLIC_GOVERNMENT_DATA",
                access_method="REST_API",
                geographic_coverage="INDIA_COASTAL_AND_MAJOR_PORTS",
                update_characteristics="MONTHLY_REGISTRY_UPDATE",
                reliability_limitations="SUBJECT_TO_PORT_AUTHORITY_REPORTING_CYCLES",
                attribution="shipmin.gov.in, sagarmala.gov.in, mmb.gov.in",
                connector="marine_intelligence_connector",
                last_validation=datetime.now(timezone.utc).isoformat(),
                status=SourceStatus.ACTIVE,
                provenance_reference={"provider": "Ministry of Ports, Shipping and Waterways", "repository": "https://github.com/shravani2207-tech/marine-intelligence-task", "commit": "03af9e32eeba275592a8e19041d7b51d6139dad7"},
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-celestrak",
                name="God's Eye View - CelesTrak Satellite Ephemeris TLE Feeds",
                authority="CelesTrak / Dr. T.S. Kelso",
                source_type="SATELLITE_NORAD_TLE_CATALOG",
                licence="US_GOVERNMENT_PUBLIC_DOMAIN",
                access_method="REST_API_PROXY",
                geographic_coverage="GLOBAL_ORBITAL",
                update_characteristics="DAILY_CATALOG_REFRESH",
                reliability_limitations="SGP4_PROPAGATION_DECAY_LATENCY",
                attribution="CelesTrak (celestrak.org), Dr. T.S. Kelso",
                connector="gods_eye_view_connector",
                last_validation=datetime.now(timezone.utc).isoformat(),
                status=SourceStatus.ACTIVE,
                provenance_reference={"provider": "CelesTrak", "repository": "https://github.com/bilawalsidhu/gods-eye-view", "commit": "e7707d9a0f34d9fbffc300023c319f95caa5be30"},
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-nifc-firms",
                name="God's Eye View - NIFC WFIGS & NASA FIRMS Wildfire Data",
                authority="National Interagency Fire Center (NIFC) / NASA LANCE FIRMS",
                source_type="NASA_FIRMS_ACTIVE_FIRE_CSV",
                licence="US_GOVERNMENT_PUBLIC_DOMAIN",
                access_method="REST_API_PROXY",
                geographic_coverage="NORTH_AMERICA_GLOBAL_THERMAL",
                update_characteristics="NASA_VIIRS_NEAR_REAL_TIME; GODS_EYE_VIEW_30_MINUTE_SERVER_CACHE",
                reliability_limitations="AGENCY_REPORTING_DELAY_AND_CLOUD_THERMAL_BLINDNESS",
                attribution="Active fire detections: NASA LANCE FIRMS; wildfire perimeters: NIFC WFIGS",
                connector="integrations.firms_active_fire_connector",
                last_validation="NOT VERIFIED",
                status=SourceStatus.ACTIVE,
                provenance_reference={"provider": "NIFC WFIGS / NASA FIRMS", "repository": "https://github.com/bilawalsidhu/gods-eye-view", "commit": "e7707d9a0f34d9fbffc300023c319f95caa5be30"},
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-tomtom-traffic",
                name="God's Eye View - TomTom Live Traffic Flow",
                authority="TomTom Traffic API",
                source_type="TRAFFIC_FLOW_VECTOR_TILES",
                licence="TOMTOM_API_TERMS",
                access_method="SERVER_SIDE_REST_API_KEY",
                geographic_coverage="TOMTOM_TRAFFIC_FLOW_COVERAGE; VERIFIED_PER_REQUESTED_TILE",
                update_characteristics="REAL_TIME_FLOW_TILES; GODS_EYE_VIEW_120_SECOND_CACHE",
                reliability_limitations="TILE_COVERAGE_VARIES_BY_ZOOM_AND_ROAD_CLASS; RELATIVE_FLOW_HAS_NO_ABSOLUTE_SPEEDS",
                attribution="Traffic flow data © TomTom",
                connector="integrations.tomtom_traffic_connector",
                last_validation="NOT VERIFIED",
                status=SourceStatus.ACTIVE,
                provenance_reference={"provider": "TomTom Traffic API", "repository": "https://github.com/bilawalsidhu/gods-eye-view", "path": "server/providers/traffic.js"},
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-noaa-weather",
                name="God's Eye View - NOAA GFS & nowCOAST Meteorological Services",
                authority="NOAA National Weather Service / National Environmental Satellite Service",
                source_type="WEATHER_GRIB2_AND_WMS_RASTER",
                licence="US_PUBLIC_DOMAIN",
                access_method="S3_BYTE_RANGE_AND_WMS",
                geographic_coverage="GLOBAL_AND_CONUS",
                update_characteristics="6_HOURLY_GFS_CYCLE_4_MINUTE_NOWCOAST_RADAR",
                reliability_limitations="GRID_INTERPOLATION_AND_RADAR_BEAM_BLOCKAGE",
                attribution="NOAA Global Forecast System (GFS) / NOAA nowCOAST",
                connector="gods_eye_view_connector",
                last_validation=datetime.now(timezone.utc).isoformat(),
                status=SourceStatus.ACTIVE,
                provenance_reference={"provider": "NOAA NWS", "repository": "https://github.com/bilawalsidhu/gods-eye-view", "commit": "e7707d9a0f34d9fbffc300023c319f95caa5be30"},
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-gfs-wind",
                name="God's Eye View - NOAA GFS Point Wind Forecasts",
                authority="NOAA National Centers for Environmental Prediction",
                source_type="GLOBAL_NUMERICAL_WEATHER_FORECAST",
                licence="US_PUBLIC_DOMAIN",
                access_method="GODS_EYE_VIEW_WIND_MANIFEST_AND_GRID",
                geographic_coverage="GLOBAL; POINT_COVERAGE_RECORDED_PER_INGEST",
                update_characteristics="6_HOURLY_GFS_FORECAST_CYCLES",
                reliability_limitations="GRIDDED_MODEL_FORECAST_SAMPLED_TO_REQUESTED_POINTS; NOT_CURRENT_OBSERVATIONS",
                attribution="NOAA Global Forecast System via God's Eye View",
                connector="integrations.weather_connector.fetch_wind_forecasts",
                last_validation="NOT VERIFIED",
                status=SourceStatus.ACTIVE,
                provenance_reference={"provider": "NOAA GFS via God's Eye View", "repository": "https://github.com/bilawalsidhu/gods-eye-view", "path": "server/providers/wind.js", "last_fetch_status": "NOT VERIFIED"},
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-ecmwf-wind",
                name="God's Eye View - ECMWF IFS Point Wind Forecasts",
                authority="European Centre for Medium-Range Weather Forecasts",
                source_type="GLOBAL_NUMERICAL_WEATHER_FORECAST",
                licence="CC_BY_4_0_AND_ECMWF_TERMS",
                access_method="GODS_EYE_VIEW_WIND_MANIFEST_AND_GRID",
                geographic_coverage="GLOBAL; POINT_COVERAGE_RECORDED_PER_INGEST",
                update_characteristics="ECMWF_OPEN_DATA_FORECAST_CYCLES",
                reliability_limitations="GRIDDED_MODEL_FORECAST_SAMPLED_TO_REQUESTED_POINTS; NOT_CURRENT_OBSERVATIONS",
                attribution="ECMWF Open Data via God's Eye View",
                connector="integrations.weather_connector.fetch_wind_forecasts",
                last_validation="NOT VERIFIED",
                status=SourceStatus.ACTIVE,
                provenance_reference={"provider": "ECMWF IFS via God's Eye View", "repository": "https://github.com/bilawalsidhu/gods-eye-view", "path": "server/providers/wind.js", "last_fetch_status": "NOT VERIFIED"},
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-open-meteo-current-weather",
                name="Open-Meteo Current Surface Weather",
                authority="Open-Meteo",
                source_type="CURRENT_MODEL_WEATHER_CONDITIONS",
                licence="CC_BY_4_0",
                access_method="REST_API",
                geographic_coverage="GLOBAL; POINT_COVERAGE_RECORDED_PER_INGEST",
                update_characteristics="HOURLY_CURRENT_CONDITIONS_MODEL_UPDATE",
                reliability_limitations="MODEL_DERIVED_CURRENT_CONDITIONS; NOT_STATION_OBSERVATIONS",
                attribution="Weather data by Open-Meteo.com",
                connector="integrations.weather_connector.fetch_open_meteo_current",
                last_validation="NOT VERIFIED",
                status=SourceStatus.ACTIVE,
                provenance_reference={"provider": "Open-Meteo", "endpoint": "https://api.open-meteo.com/v1/forecast", "repository": "https://github.com/bilawalsidhu/gods-eye-view", "path": "server/providers/regional/weather.js", "last_fetch_status": "NOT VERIFIED"},
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-noaa-nowcoast-radar",
                name="God's Eye View - NOAA nowCOAST CONUS Base Reflectivity Radar",
                authority="NOAA/NWS nowCOAST",
                source_type="GEOSPATIAL_WEATHER_RADAR_WMS",
                licence="NOAA_PUBLIC_DATA; NOAA_NOWCOAST_TERMS",
                access_method="WMS_IMAGE_AND_GEOGRAPHIC_TILES_VIA_GODS_EYE_VIEW",
                geographic_coverage="CONTIGUOUS_UNITED_STATES; BOUNDS_FROM_LIVE_WMS_CAPABILITIES",
                update_characteristics="MRMS_RADAR_BASE_REFLECTIVITY_APPROX_1_KM; APPROX_4_MINUTE_UPDATES; AVAILABLE_TIMES_FROM_WMS_CAPABILITIES",
                reliability_limitations="OBSERVED_REFLECTIVITY_NOT_RAINFALL_FORECAST; SPATIAL_GAPS_DO_NOT_MEAN_NO_PRECIPITATION",
                attribution="NOAA/NWS nowCOAST",
                connector="integrations.noaa_radar_connector",
                last_validation="NOT VERIFIED",
                status=SourceStatus.ACTIVE,
                provenance_reference={"provider": "NOAA nowCOAST", "service": "weather_radar", "layer": "conus_base_reflectivity_mosaic", "product": "radar", "repository": "https://github.com/bilawalsidhu/gods-eye-view", "path": "server/providers/weather.js", "last_fetch_status": "NOT VERIFIED"},
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-noaa-nowcoast-clouds-global",
                name="God's Eye View - NOAA nowCOAST Global Satellite Infrared Imagery",
                authority="NOAA/NWS/NESDIS nowCOAST",
                source_type="GEOSPATIAL_SATELLITE_INFRARED_WMS",
                licence="NOAA_PUBLIC_DATA; NOAA_NOWCOAST_TERMS",
                access_method="WMS_IMAGE_AND_GEOGRAPHIC_TILES_VIA_GODS_EYE_VIEW",
                geographic_coverage="GLOBAL_MOSAIC_INCOMPLETE_POLAR_COVERAGE; LIVE_BOUNDS_FROM_WMS_CAPABILITIES",
                update_characteristics="GLOBAL_LONGWAVE_INFRARED_MOSAIC; HOURLY_SOURCE_UPDATES_WITH_2_TO_3_HOUR_LATENCY; LIVE_TIMESTAMPS_FROM_WMS_CAPABILITIES",
                reliability_limitations="INFRARED_CLOUD_AND_LAND_SEA_TEMPERATURE_PATTERNS; NOT_A_CLOUD_ONLY_MASK",
                attribution="NOAA/NWS/NESDIS nowCOAST",
                connector="integrations.noaa_radar_connector.fetch_weather_manifest",
                last_validation="NOT VERIFIED",
                status=SourceStatus.ACTIVE,
                provenance_reference={"provider": "NOAA nowCOAST", "service": "satellite", "layer": "global_longwave_imagery_mosaic", "product": "clouds", "repository": "https://github.com/bilawalsidhu/gods-eye-view", "path": "server/providers/weather.js", "last_fetch_status": "NOT VERIFIED"},
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-noaa-nowcoast-clouds-regional",
                name="God's Eye View - NOAA nowCOAST GOES Regional Satellite Infrared Imagery",
                authority="NOAA/NWS/NESDIS nowCOAST",
                source_type="GEOSPATIAL_SATELLITE_INFRARED_WMS",
                licence="NOAA_PUBLIC_DATA; NOAA_NOWCOAST_TERMS",
                access_method="WMS_IMAGE_AND_GEOGRAPHIC_TILES_VIA_GODS_EYE_VIEW",
                geographic_coverage="GOES_EAST_WEST_REGIONAL_NORTH_AMERICA; LIVE_BOUNDS_FROM_WMS_CAPABILITIES",
                update_characteristics="GOES_19_18_LONGWAVE_IR_BAND_14; APPROX_5_MINUTE_UPDATES; LIVE_TIMESTAMPS_FROM_WMS_CAPABILITIES",
                reliability_limitations="INFRARED_CLOUD_AND_SURFACE_TEMPERATURE_PATTERNS; NOT_A_CLOUD_ONLY_MASK",
                attribution="NOAA/NWS/NESDIS nowCOAST",
                connector="integrations.noaa_radar_connector.fetch_weather_manifest",
                last_validation="NOT VERIFIED",
                status=SourceStatus.ACTIVE,
                provenance_reference={"provider": "NOAA nowCOAST", "service": "satellite", "layer": "goes_longwave_imagery", "product": "clouds-regional", "repository": "https://github.com/bilawalsidhu/gods-eye-view", "path": "server/providers/weather.js", "last_fetch_status": "NOT VERIFIED"},
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-noaa-nowcoast-lightning",
                name="God's Eye View - NOAA nowCOAST Lightning Strike Density Imagery",
                authority="NOAA/NWS nowCOAST",
                source_type="GEOSPATIAL_LIGHTNING_DENSITY_WMS",
                licence="NOAA_PUBLIC_DATA; NOAA_NOWCOAST_TERMS",
                access_method="WMS_IMAGE_AND_GEOGRAPHIC_TILES_VIA_GODS_EYE_VIEW",
                geographic_coverage="PACIFIC_AND_AMERICAS_ACROSS_DATELINE; LIVE_BOUNDS_FROM_WMS_CAPABILITIES",
                update_characteristics="OBSERVED_15_MINUTE_LIGHTNING_STRIKE_DENSITY; APPROX_8_KM_GRID; LIVE_TIMESTAMPS_FROM_WMS_CAPABILITIES",
                reliability_limitations="DENSITY_DERIVED_FROM_GROUND_NETWORKS; NOT_INDIVIDUAL_GLM_FLASHES; NETWORK_COVERAGE_VARIES",
                attribution="NOAA/NWS nowCOAST; derived from Vaisala NLDN/GLD360",
                connector="integrations.noaa_radar_connector.fetch_weather_manifest",
                last_validation="NOT VERIFIED",
                status=SourceStatus.ACTIVE,
                provenance_reference={"provider": "NOAA nowCOAST", "service": "lightning_detection", "layer": "ldn_lightning_strike_density", "product": "lightning", "repository": "https://github.com/bilawalsidhu/gods-eye-view", "path": "server/providers/weather.js", "last_fetch_status": "NOT VERIFIED"},
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-noaa-nhc-cyclone-status",
                name="God's Eye View - NOAA NHC/CPHC Current Tropical Cyclone Status",
                authority="NOAA National Hurricane Center / Central Pacific Hurricane Center",
                source_type="CURRENT_TROPICAL_CYCLONE_ADVISORY_JSON",
                licence="US_GOVERNMENT_PUBLIC_DOMAIN",
                access_method="NOAA_CURRENTSTORMS_JSON_VIA_GODS_EYE_VIEW",
                geographic_coverage="ATLANTIC_AND_EASTERN_CENTRAL_NORTH_PACIFIC; NOT_WORLDWIDE",
                update_characteristics="CURRENT_ADVISORY_AND_STORM_POSITION; PROVIDER_REFRESHES_WITH_5_MINUTE_CACHE",
                reliability_limitations="ADVISORY_POSITIONS_AND_INTENSITY_ARE_SUBJECT_TO_OFFICIAL_REVISION; ONLY_ACTIVE_STORMS",
                attribution="NOAA/NWS National Hurricane Center / Central Pacific Hurricane Center",
                connector="integrations.noaa_cyclone_connector.fetch_current_cyclones",
                last_validation="NOT VERIFIED",
                status=SourceStatus.ACTIVE,
                provenance_reference={"provider": "NOAA NHC / CPHC", "upstream": "https://www.nhc.noaa.gov/CurrentStorms.json", "repository": "https://github.com/bilawalsidhu/gods-eye-view", "path": "server/providers/cyclones.js", "last_fetch_status": "NOT VERIFIED"},
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-noaa-nhc-cyclone-points",
                name="NOAA Tropical Weather GIS - Cyclone Forecast Points",
                authority="NOAA National Hurricane Center / NOAA Weather GIS",
                source_type="GEOSPATIAL_CYCLONE_FORECAST_POINT_FEATURES",
                licence="US_GOVERNMENT_PUBLIC_DOMAIN",
                access_method="ARCGIS_REST_GEOJSON_VIA_GODS_EYE_VIEW",
                geographic_coverage="ATLANTIC_AND_EASTERN_CENTRAL_NORTH_PACIFIC; NOT_WORLDWIDE",
                update_characteristics="ADVISORY_FORECAST_POINTS_FROM_GIS_LAYER_5",
                reliability_limitations="FEATURES_MATCH_CURRENT_STORM_ADVISORY; MAY_BE_EMPTY_WHEN_NO_ACTIVE_STORM_POINTS",
                attribution="NOAA/NWS National Hurricane Center / Central Pacific Hurricane Center",
                connector="integrations.noaa_cyclone_connector.fetch_current_cyclones",
                last_validation="NOT VERIFIED",
                status=SourceStatus.ACTIVE,
                provenance_reference={"provider": "NOAA Tropical Weather GIS", "service": "NHC_tropical_weather_summary/MapServer/5", "repository": "https://github.com/bilawalsidhu/gods-eye-view", "path": "server/providers/cyclones.js", "last_fetch_status": "NOT VERIFIED"},
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-noaa-nhc-cyclone-tracks",
                name="NOAA Tropical Weather GIS - Cyclone Storm Tracks",
                authority="NOAA National Hurricane Center / NOAA Weather GIS",
                source_type="GEOSPATIAL_CYCLONE_TRACK_FEATURES",
                licence="US_GOVERNMENT_PUBLIC_DOMAIN",
                access_method="ARCGIS_REST_GEOJSON_VIA_GODS_EYE_VIEW",
                geographic_coverage="ATLANTIC_AND_EASTERN_CENTRAL_NORTH_PACIFIC; NOT_WORLDWIDE",
                update_characteristics="ADVISORY_STORM_TRACKS_FROM_GIS_LAYER_6",
                reliability_limitations="FEATURES_MATCH_CURRENT_STORM_ADVISORY; MAY_BE_EMPTY_WHEN_NO_ACTIVE_TRACKS",
                attribution="NOAA/NWS National Hurricane Center / Central Pacific Hurricane Center",
                connector="integrations.noaa_cyclone_connector.fetch_current_cyclones",
                last_validation="NOT VERIFIED",
                status=SourceStatus.ACTIVE,
                provenance_reference={"provider": "NOAA Tropical Weather GIS", "service": "NHC_tropical_weather_summary/MapServer/6", "repository": "https://github.com/bilawalsidhu/gods-eye-view", "path": "server/providers/cyclones.js", "last_fetch_status": "NOT VERIFIED"},
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-noaa-nhc-cyclone-cones",
                name="NOAA Tropical Weather GIS - Cyclone Forecast Cones",
                authority="NOAA National Hurricane Center / NOAA Weather GIS",
                source_type="GEOSPATIAL_CYCLONE_FORECAST_CONE_FEATURES",
                licence="US_GOVERNMENT_PUBLIC_DOMAIN",
                access_method="ARCGIS_REST_GEOJSON_VIA_GODS_EYE_VIEW",
                geographic_coverage="ATLANTIC_AND_EASTERN_CENTRAL_NORTH_PACIFIC; NOT_WORLDWIDE",
                update_characteristics="ADVISORY_FORECAST_CONES_FROM_GIS_LAYER_7",
                reliability_limitations="CONE_IS_FORECAST_TRACK_UNCERTAINTY_NOT_STORM_SIZE; MAY_BE_EMPTY",
                attribution="NOAA/NWS National Hurricane Center / Central Pacific Hurricane Center",
                connector="integrations.noaa_cyclone_connector.fetch_current_cyclones",
                last_validation="NOT VERIFIED",
                status=SourceStatus.ACTIVE,
                provenance_reference={"provider": "NOAA Tropical Weather GIS", "service": "NHC_tropical_weather_summary/MapServer/7", "repository": "https://github.com/bilawalsidhu/gods-eye-view", "path": "server/providers/cyclones.js", "last_fetch_status": "NOT VERIFIED"},
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-usgs-seismic",
                name="God's Eye View - USGS Earthquake Hazards Program Feeds",
                authority="U.S. Geological Survey (USGS)",
                source_type="SEISMIC_EVENT_FEED",
                licence="US_GOVERNMENT_PUBLIC_DOMAIN",
                access_method="REST_GEOJSON",
                geographic_coverage="GLOBAL",
                update_characteristics="1_MINUTE_GEOJSON_POLL",
                reliability_limitations="PRELIMINARY_AUTOMATED_MAGNITUDE_REVISIONS",
                attribution="Data courtesy of the U.S. Geological Survey",
                connector="gods_eye_view_connector",
                last_validation="NOT VERIFIED",
                status=SourceStatus.ACTIVE,
                provenance_reference={"provider": "USGS", "repository": "https://github.com/bilawalsidhu/gods-eye-view", "commit": "e7707d9a0f34d9fbffc300023c319f95caa5be30", "dataset_id": "ds-gev-seismic-events", "last_fetch_status": "PENDING", "credential_values_stored": False},
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-aisstream-vessels",
                name="God's Eye View - AISStream Vessel Positions",
                authority="AISStream.io",
                source_type="LIVE_AIS_POSITION_REPORTS",
                licence="UNSPECIFIED",
                access_method="AUTHENTICATED_WEBSOCKET",
                geographic_coverage="BOUNDED_BY_REQUESTED_SUBSCRIPTION_BOXES",
                update_characteristics="LIVE_POSITION_REPORTS; REQUEST_BOUNDED_BATCHES",
                reliability_limitations="REQUIRES_VALID_AISSTREAM_CREDENTIAL_AND_CONFIGURED_BOUNDS; AIS_REPORTS_MAY_BE_SPARSE",
                attribution="AISStream.io (courtesy)",
                connector="integrations.aisstream_connector.fetch_aisstream_positions",
                last_validation="NOT VERIFIED",
                status=SourceStatus.ACTIVE,
                provenance_reference={"provider": "AISStream.io", "repository": "https://github.com/bilawalsidhu/gods-eye-view", "path": "server/providers/vessels/ais-live.js", "dataset_id": "aisstream_vessel_positions", "data_mode": "LIVE_OBSERVATIONS", "last_fetch_status": "PENDING", "credential_values_stored": False},
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-adsb-military",
                name="God's Eye View - adsb.lol Military Aircraft Positions",
                authority="adsb.lol contributors",
                source_type="LIVE_ADSB_AIRCRAFT_OBSERVATIONS",
                licence="ODBL_1_0",
                access_method="REST_API",
                geographic_coverage="MILITARY_AIRCRAFT_PUBLISHED_BY_ADSB_LOL",
                update_characteristics="LIVE_SNAPSHOT_PER_INGEST_REQUEST",
                reliability_limitations="COVERAGE_DEPENDS_ON_RECEIVER_NETWORK_AND_AIRCRAFT_TRANSPONDERS; NOT_AUTHORITATIVE",
                attribution="adsb.lol contributors (ODbL)",
                connector="integrations.adsb_military_connector.fetch_military_aircraft",
                last_validation="NOT VERIFIED",
                status=SourceStatus.ACTIVE,
                provenance_reference={"provider": "adsb.lol", "endpoint": "https://api.adsb.lol/v2/mil", "repository": "https://github.com/bilawalsidhu/gods-eye-view", "path": "server/providers/aircraft/adsb-lol.js", "dataset_id": "adsb_military_aircraft_observations", "data_mode": "LIVE_OBSERVATIONS", "last_fetch_status": "PENDING", "credential_values_stored": False},
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-openinframap-dams",
                name="God's Eye View - OpenInfraMap Dams Snapshot",
                authority="OpenStreetMap contributors / Open Infrastructure Map",
                source_type="STATIC_GEOJSONL_INFRASTRUCTURE_FEATURES",
                licence="ODBL_1_0",
                access_method="BUNDLED_GEOJSONL_SNAPSHOT",
                geographic_coverage="GLOBAL; COVERAGE LIMITED TO FEATURES IN SOURCE SNAPSHOT",
                update_characteristics="STATIC_SNAPSHOT; NO AUTOMATIC REFRESH SCHEDULE",
                reliability_limitations="SOURCE SNAPSHOT MAY BE INCOMPLETE OR STALE; OSM TAGGING VARIES",
                attribution="© OpenStreetMap contributors; Open Infrastructure Map",
                connector="integrations.gods_eye_view_dams_connector.fetch_dams",
                last_validation="NOT VERIFIED",
                status=SourceStatus.ACTIVE,
                provenance_reference={
                    "provider": "God's Eye View / OpenInfraMap",
                    "repository": "https://github.com/bilawalsidhu/gods-eye-view",
                    "path": "src/data/local_data/dams/dams.geojsonl",
                    "companion_source": "src/data/local_data/dams/dams.geojson",
                    "source_feature_count": 704,
                    "data_mode": "STATIC_SNAPSHOT",
                    "last_fetch_status": "NOT VERIFIED",
                },
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-bhote-koshi-flood",
                name="God's Eye View - Bhote Koshi Historical Flood Reconstruction",
                authority="GeoPera / Vantor Open Data / linked public witness sources",
                source_type="STATIC_HISTORICAL_FLOOD_RECONSTRUCTION",
                licence="MIXED_CC_BY_NC_4_0_AND_LINKED_THIRD_PARTY_TERMS",
                access_method="BUNDLED_EVENT_JSON_AND_SOURCE_MODULES",
                geographic_coverage="BHOTE_KOSHI_TO_TRISHULI_CORRIDOR; SOURCE_EVENT_POINTS_AND_FLOOD_PATH",
                update_characteristics="STATIC_HISTORICAL_RECONSTRUCTION; NO AUTOMATIC REFRESH SCHEDULE",
                reliability_limitations="SCHEMATIC_RECONSTRUCTION_NOT_AN_OFFICIAL_HAZARD_MODEL; WITNESS CAPTURE TIMES UNVERIFIED; MEDIA IS LINKED NOT REDISTRIBUTED",
                attribution="GeoPera reconstruction (CC BY-NC 4.0); Vantor Open Data imagery; linked witness posts retain their owners' terms",
                connector="integrations.gods_eye_view_bhote_koshi_connector.fetch_bhote_koshi_event",
                last_validation="NOT VERIFIED",
                status=SourceStatus.ACTIVE,
                provenance_reference={
                    "provider": "God's Eye View / GeoPera / Vantor Open Data",
                    "repository": "https://github.com/bilawalsidhu/gods-eye-view",
                    "source_files": [
                        "src/data/bhoteKoshiFloodPath.js",
                        "src/data/bhoteKoshiEvent.js",
                        "src/data/bhoteKoshiEmbeddedMedia.js",
                        "public/events/bhote-koshi-2026/event.json",
                    ],
                    "data_mode": "STATIC_HISTORICAL_RECONSTRUCTION",
                    "last_fetch_status": "NOT VERIFIED",
                    "capture_times": "UNVERIFIED_WHERE_NULL_IN_SOURCE",
                    "media_mode": "EXTERNAL_LINK_METADATA_ONLY",
                },
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-google-photoreal-tiles",
                name="God's Eye View - Google Photorealistic 3D Tiles",
                authority="Google Maps Platform / Cesium ion",
                source_type="PHOTOREALISTIC_3D_TILES_SERVICE",
                licence="GOOGLE_MAPS_PLATFORM_TERMS_AND_CESIUM_ION_TERMS",
                access_method="CESIUMJS_GOOGLE_DIRECT_OR_CESIUM_ION_ASSET",
                geographic_coverage="GLOBAL_WHERE_GOOGLE_PHOTOREALISTIC_3D_COVERAGE_IS_AVAILABLE",
                update_characteristics="PROVIDER_HOSTED_STREAMING_3D_TILES; REFRESHED_BY_PROVIDER",
                reliability_limitations="COVERAGE_AND_ACCESS_DEPEND_ON_PROVIDER; GOOGLE_OR_CESIUM_CREDENTIALS_REQUIRED; NO_TILE_ARCHIVE_IN_MASTERDB",
                attribution="Google Maps Platform per-tile credits must remain visible; Cesium ion attribution applies on the hosted asset route",
                connector="integrations.gods_eye_view_photoreal_tiles_connector.verify_photoreal_tiles",
                last_validation="NOT VERIFIED",
                status=SourceStatus.ACTIVE,
                provenance_reference={
                    "provider": "Google Maps Platform Photorealistic 3D Tiles via CesiumJS",
                    "repository": "https://github.com/bilawalsidhu/gods-eye-view",
                    "source_files": ["src/maps/google3d.js", "src/maps/defaultSources.js", "src/main.js", "server/standalone/vite.config.js"],
                    "google_direct_root_endpoint": "https://tile.googleapis.com/v1/3dtiles/root.json",
                    "cesium_ion_asset_id": 2275207,
                    "cesium_ion_endpoint": "https://api.cesium.com/v1/assets/2275207/endpoint",
                    "data_mode": "EXTERNAL_GEOPATIAL_TILE_SERVICE",
                    "last_fetch_status": "NOT VERIFIED",
                    "credential_values_stored": False,
                },
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-world-satellite-imagery",
                name="God's Eye View - World Satellite Imagery Basemap",
                authority="Esri / Cesium ion / OpenStreetMap contributors",
                source_type="WORLD_SATELLITE_IMAGERY_TILE_SERVICE",
                licence="ESRI_WORLD_IMAGERY_TERMS; CESIUM_ION_TERMS; OSM_ODBL_1_0",
                access_method="EXTERNAL_XYZ_AND_ARCGIS_TILE_SERVICES",
                geographic_coverage="GLOBAL; IMAGERY AVAILABILITY AND RESOLUTION VARY BY LOCATION AND PROVIDER",
                update_characteristics="PROVIDER_HOSTED_IMAGERY; REFRESHED_BY_PROVIDER",
                reliability_limitations="PROVIDER_COVERAGE_AND_AVAILABILITY_VARY; CESIUM_ION_REQUIRES_TOKEN; NO_TILE_ARCHIVE_IN_MASTERDB",
                attribution="Powered by Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community; fallback © OpenStreetMap contributors. Cesium ion attribution applies when ion imagery is used.",
                connector="integrations.gods_eye_view_satellite_imagery_connector.verify_satellite_imagery",
                last_validation="NOT VERIFIED",
                status=SourceStatus.ACTIVE,
                provenance_reference={
                    "provider": "Esri World Imagery; Cesium ion imagery fallback; OpenStreetMap Standard Tiles fallback",
                    "repository": "https://github.com/bilawalsidhu/gods-eye-view",
                    "path": "src/maps/imagery.js",
                    "esri_endpoint": "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer",
                    "osm_endpoint": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
                    "data_mode": "EXTERNAL_GEOPATIAL_TILE_SERVICE",
                    "last_fetch_status": "NOT VERIFIED",
                    "credential_values_stored": False,
                },
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-world-3d-terrain",
                name="God's Eye View - World 3D Terrain",
                authority="Re:Earth Terrain / Mapterhorn; Cesium ion for optional Cesium World Terrain",
                source_type="QUANTIZED_MESH_TERRAIN_TILE_SERVICE",
                licence="RE_EARTH_MAPTERHORN_CC_BY_4_0; EGM2008_NGA_PUBLIC_DOMAIN; CESIUM_ION_TERMS_WHEN_CONFIGURED",
                access_method="CESIUM_QUANTIZED_MESH_TILES",
                geographic_coverage="PROVIDER_DEFINED; COVERAGE METADATA MAY BE REPORTED BY LAYER.JSON",
                update_characteristics="PROVIDER_HOSTED_TERRAIN_MESH; PROVIDER_MAINTAINED",
                reliability_limitations="KEYLESS_REEARTH_ENDPOINT_MAY_THROTTLE_OR_BE_UNAVAILABLE; CESIUM_ION_WORLD_TERRAIN_REQUIRES_CESIUM_ION_TOKEN; FLAT_ELLIPSOID_IS_NOT_TERRAIN_DATA",
                attribution="Terrain (keyless globe stacks): Re:Earth Terrain / Mapterhorn (CC BY 4.0) / EGM2008 (NGA); Cesium ion attribution is supplied by CesiumJS when ion terrain is active.",
                connector="integrations.gods_eye_view_terrain_connector.verify_world_terrain",
                last_validation="NOT VERIFIED",
                status=SourceStatus.ACTIVE,
                provenance_reference={
                    "provider": "Re:Earth Terrain / Mapterhorn; optional Cesium World Terrain via Cesium ion",
                    "repository": "https://github.com/bilawalsidhu/gods-eye-view",
                    "path": "src/maps/terrain.js",
                    "keyless_endpoint": "https://terrain.reearth.land/cesium-mesh/ellipsoid",
                    "cesium_ion_asset_id": 1,
                    "cesium_ion_endpoint": "https://api.cesium.com/v1/assets/1/endpoint",
                    "format": "CESIUM_QUANTIZED_MESH",
                    "data_mode": "EXTERNAL_GEOPATIAL_TERRAIN_SERVICE",
                    "last_fetch_status": "NOT VERIFIED",
                    "credential_values_stored": False,
                },
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-openfreemap-vector-basemap",
                name="God's Eye View - OpenFreeMap Vector Basemap Tiles",
                authority="OpenFreeMap / OpenMapTiles / OpenStreetMap contributors",
                source_type="MAPBOX_VECTOR_TILE_SERVICE",
                licence="OPENSTREETMAP_ODBL_1_0; OPENFREEMAP_AND_OPENMAPTILES_ATTRIBUTION_REQUIRED",
                access_method="TILEJSON_AND_MAPBOX_VECTOR_TILES",
                geographic_coverage="LIVE_TILEJSON_BOUNDS_AND_ZOOM_RANGE",
                update_characteristics="PROVIDER_HOSTED_PLANET_TILES; TILEJSON TEMPLATE VERSIONED BY PROVIDER",
                reliability_limitations="PUBLIC_TILE_SERVICE_MAY_RATE_LIMIT_OR_BE_UNAVAILABLE; NO SILENT_TILE_ORIGIN_FALLBACK",
                attribution="OpenFreeMap © OpenMapTiles; Data from OpenStreetMap",
                connector="integrations.gods_eye_view_vector_basemap_connector.verify_vector_basemap",
                last_validation="NOT VERIFIED",
                status=SourceStatus.ACTIVE,
                provenance_reference={
                    "provider": "OpenFreeMap / OpenMapTiles",
                    "repository": "https://github.com/bilawalsidhu/gods-eye-view",
                    "path": "src/sources/openFreeMap.js",
                    "tilejson_endpoint": "https://tiles.openfreemap.org/planet",
                    "tile_url_template": "RESOLVED_FROM_LIVE_TILEJSON",
                    "consumed_vector_layers": ["transportation", "landuse"],
                    "style_url": None,
                    "style_note": "God's Eye View decodes vector data; its OpenFreeMap source does not configure a cartographic style URL.",
                    "fallback_workflow": "OpenFreeMap roads are primary without TomTom; Hybrid uses OpenFreeMap where TomTom has no flow. The tile source does not silently switch origins.",
                    "data_mode": "EXTERNAL_GEOPATIAL_VECTOR_TILE_SERVICE",
                    "last_fetch_status": "NOT VERIFIED",
                    "credential_values_stored": False,
                },
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-natural-earth-regions",
                name="Natural Earth 10m Physical Geography Regions",
                authority="Natural Earth",
                source_type="STATIC_NATURAL_EARTH_POLYGON_DATASET",
                licence="PUBLIC_DOMAIN_NATURAL_EARTH",
                access_method="BUNDLED_JSON_SNAPSHOT",
                geographic_coverage="GLOBAL; EXTENT IS DEFINED BY VALIDATED SOURCE GEOMETRIES",
                update_characteristics="STATIC_SNAPSHOT; SOURCE METADATA FETCHED 2026-07-28; NATURAL EARTH DATA COMMIT ca96624a56bd078437bca8184e78163e5039ad19",
                reliability_limitations="CURATED_10M_PHYSICAL_VECTORS; OUTER_RINGS_ONLY; SOURCE FEATURES HAVE NO NATURAL_EARTH_ID",
                attribution="Natural Earth (naturalearthdata.com); public domain.",
                connector="integrations.natural_earth_connector.load_natural_earth_source",
                last_validation="NOT VERIFIED",
                status=SourceStatus.ACTIVE,
                provenance_reference={
                    "provider": "Natural Earth 10m physical vectors — ne_10m_geography_regions_polys",
                    "dataset_id": "gods_eye_view_natural_earth_regions",
                    "repository": "https://github.com/bilawalsidhu/gods-eye-view",
                    "path": "src/data/local_data/natural_earth/regions.json",
                    "upstream_url": "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/ca96624a56bd078437bca8184e78163e5039ad19/geojson/ne_10m_geography_regions_polys.geojson",
                    "upstream_commit": "ca96624a56bd078437bca8184e78163e5039ad19",
                    "feature_count_from_source_metadata": 1046,
                    "data_mode": "STATIC_SNAPSHOT",
                    "last_fetch_status": "NOT VERIFIED",
                    "credential_values_stored": False,
                },
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-natural-earth-marine",
                name="Natural Earth 10m Physical Marine Features",
                authority="Natural Earth",
                source_type="STATIC_NATURAL_EARTH_POLYGON_DATASET",
                licence="PUBLIC_DOMAIN_NATURAL_EARTH",
                access_method="BUNDLED_JSON_SNAPSHOT",
                geographic_coverage="GLOBAL; EXTENT IS DEFINED BY VALIDATED SOURCE GEOMETRIES",
                update_characteristics="STATIC_SNAPSHOT; SOURCE METADATA FETCHED 2026-07-28; NATURAL EARTH DATA COMMIT ca96624a56bd078437bca8184e78163e5039ad19",
                reliability_limitations="CURATED_10M_PHYSICAL_VECTORS; OUTER_RINGS_ONLY; SOURCE FEATURES HAVE NO NATURAL_EARTH_ID",
                attribution="Natural Earth (naturalearthdata.com); public domain.",
                connector="integrations.natural_earth_connector.load_natural_earth_source",
                last_validation="NOT VERIFIED",
                status=SourceStatus.ACTIVE,
                provenance_reference={
                    "provider": "Natural Earth 10m physical vectors — ne_10m_geography_marine_polys",
                    "dataset_id": "gods_eye_view_natural_earth_marine",
                    "repository": "https://github.com/bilawalsidhu/gods-eye-view",
                    "path": "src/data/local_data/natural_earth/marine.json",
                    "upstream_url": "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/ca96624a56bd078437bca8184e78163e5039ad19/geojson/ne_10m_geography_marine_polys.geojson",
                    "upstream_commit": "ca96624a56bd078437bca8184e78163e5039ad19",
                    "feature_count_from_source_metadata": 292,
                    "data_mode": "STATIC_SNAPSHOT",
                    "last_fetch_status": "NOT VERIFIED",
                    "credential_values_stored": False,
                },
                write_authority_confirmed=True,
            ),
        ]
        for src in defaults:
            if not self.store.load(src.source_id):
                self.register_source(
                    SourceRegisterRequest(
                        source_id=src.source_id,
                        name=src.name,
                        authority=src.authority,
                        source_type=src.source_type,
                        licence=src.licence,
                        access_method=src.access_method,
                        geographic_coverage=src.geographic_coverage,
                        update_characteristics=src.update_characteristics,
                        reliability_limitations=src.reliability_limitations,
                        attribution=src.attribution,
                        connector=src.connector,
                        provenance_reference=src.provenance_reference,
                        confirm_write_authority=True,
                    )
                )

    def register_source(self, req: SourceRegisterRequest, actor: str = "system") -> SourceRecord:
        # Enforce license-safe restriction on commercially prohibited/unverified sources
        restricted_keywords = ["opensky", "telegeography"]
        src_id_low = (req.source_id or "").lower()
        src_name_low = (req.name or "").lower()
        if any(kw in src_id_low or kw in src_name_low for kw in restricted_keywords):
            raise ValueError(f"Registration of commercially restricted/unverified source '{req.source_id or req.name}' is prohibited.")

        # Check canonical existence / duplicate detection
        existing = self.list_sources()
        for s in existing:
            if req.source_id and s.source_id.lower() == req.source_id.lower():
                raise SourceAlreadyExistsError(f"Source with ID '{req.source_id}' already exists.")
            if s.name.lower() == req.name.lower():
                raise SourceAlreadyExistsError(f"Source with name '{req.name}' already exists.")

        # Determine authority confirmation status
        status = SourceStatus.ACTIVE if req.confirm_write_authority else SourceStatus.PENDING_AUTHORITY_CONFIRMATION
        authority_val = req.authority or "NOT VERIFIED"
        licence_val = req.licence or "PENDING"
        geographic_coverage = req.geographic_coverage or "UNKNOWN"
        update_characteristics = req.update_characteristics or "UNKNOWN"
        reliability_limitations = req.reliability_limitations or "UNKNOWN"
        attribution_val = req.attribution or "NOT VERIFIED"

        source_record = SourceRecord(
            source_id=req.source_id or f"src-{req.name.lower().replace(' ', '-')[:20]}",
            name=req.name,
            authority=authority_val,
            source_type=req.source_type or "GEOSPATIAL_PORTAL",
            licence=licence_val,
            access_method=req.access_method or "REST_API",
            geographic_coverage=geographic_coverage,
            update_characteristics=update_characteristics,
            reliability_limitations=reliability_limitations,
            attribution=attribution_val,
            connector=req.connector or "generic_connector",
            last_validation=(
                "NOT VERIFIED"
                if req.provenance_reference.get("last_fetch_status") == "NOT VERIFIED"
                else (datetime.now(timezone.utc).isoformat() if req.confirm_write_authority else "NOT VERIFIED")
            ),
            status=status,
            provenance_reference=req.provenance_reference,
            write_authority_confirmed=req.confirm_write_authority,
        )

        self.store.save(source_record.source_id, source_record.model_dump(mode="json"))

        self.audit_emitter.emit(
            event_type="source_registered",
            actor=actor,
            payload={
                "source_id": source_record.source_id,
                "name": source_record.name,
                "status": source_record.status.value,
                "write_authority_confirmed": source_record.write_authority_confirmed,
            },
        )
        logger.info(
            "source_registered source_id=%s name='%s' status=%s authority_confirmed=%s",
            source_record.source_id,
            source_record.name,
            source_record.status.value,
            source_record.write_authority_confirmed,
        )
        return source_record

    def get_source(self, source_id: str) -> SourceRecord:
        data = self.store.load(source_id)
        if not data:
            raise SourceNotFoundError(f"Source '{source_id}' not found.")
        return SourceRecord.model_validate(data)

    def mark_validated(self, source_id: str, validated_at: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> SourceRecord:
        """Persist a successful upstream validation timestamp for a source."""
        record = self.get_source(source_id)
        record.last_validation = validated_at or datetime.now(timezone.utc).isoformat()
        record.updated_at = datetime.now(timezone.utc).isoformat()
        if metadata:
            record.provenance_reference = {**record.provenance_reference, **metadata}
            if metadata.get("last_fetch_status") == "LIVE_VERIFIED":
                record.provenance_reference.pop("last_http_status", None)
        self.store.save(source_id, record.model_dump(mode="json"))
        return record

    def mark_fetch_status(self, source_id: str, status: str, metadata: Optional[Dict[str, Any]] = None) -> SourceRecord:
        """Persist sanitized upstream availability metadata without changing validation time."""
        record = self.get_source(source_id)
        record.provenance_reference = {**record.provenance_reference, "last_fetch_status": status, **(metadata or {})}
        record.updated_at = datetime.now(timezone.utc).isoformat()
        self.store.save(source_id, record.model_dump(mode="json"))
        return record

    def list_sources(self, search: Optional[str] = None, status: Optional[str] = None) -> List[SourceRecord]:
        records = self.store.list_all()
        sources: List[SourceRecord] = []
        for rec in records:
            try:
                sources.append(SourceRecord.model_validate(rec))
            except Exception as exc:
                logger.warning("Failed to parse source record: %s", exc)

        if status:
            sources = [s for s in sources if s.status.value.lower() == status.lower()]
        if search:
            s_low = search.lower()
            sources = [
                s
                for s in sources
                if s_low in s.name.lower() or s_low in s.source_id.lower() or s_low in s.authority.lower()
            ]
        return sorted(sources, key=lambda x: x.source_id)
