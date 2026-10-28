import pytest
from fastapi.testclient import TestClient

from main import app
from integrations.geospatial_connector import GeospatialConnectorAdapter
from services.opensky_service import OpenSkyService


@pytest.fixture
def client():
    return TestClient(app)


def test_opensky_global_query(client):
    """GET /api/opensky returns global flight state vectors in OpenSky 17-tuple format."""
    response = client.get("/api/opensky")
    assert response.status_code == 200
    data = response.json()
    assert "time" in data
    assert "states" in data
    assert "meta" in data
    assert "data_source_mode" in data["meta"]
    assert isinstance(data["states"], list)
    if data["states"]:
        # Verify 17-tuple format
        vector = data["states"][0]
        assert len(vector) == 17
        assert isinstance(vector[0], str)  # icao24
        assert isinstance(vector[1], str)  # callsign


def test_opensky_lat_lon_query(client):
    """GET /api/opensky?lat=<lat>&lon=<lon> returns localized flight state vectors."""
    # Test near Mumbai / Arabian Sea airspace where candidate aircraft exist
    lat, lon = 19.076, 72.8777
    response = client.get(f"/api/opensky?lat={lat}&lon={lon}&radius_nm=200")
    assert response.status_code == 200
    data = response.json()
    assert "meta" in data
    assert "filter" in data["meta"]
    filt = data["meta"]["filter"]
    assert filt["center_latitude"] == lat
    assert filt["center_longitude"] == lon
    assert filt["radius_nm"] == 200.0
    assert "bounding_box" in filt
    assert len(data["states"]) > 0

    # Validate schema of each 17-tuple state vector
    for vector in data["states"]:
        assert len(vector) == 17
        icao24 = vector[0]
        callsign = vector[1]
        origin_country = vector[2]
        longitude = vector[5]
        latitude = vector[6]
        assert isinstance(icao24, str)
        assert isinstance(callsign, str)
        assert isinstance(origin_country, str)
        assert -180.0 <= longitude <= 180.0
        assert -90.0 <= latitude <= 90.0


def test_opensky_missing_coordinate_validation(client):
    """Providing lat without lon or lon without lat returns HTTP 400 Bad Request."""
    res1 = client.get("/api/opensky?lat=19.076")
    assert res1.status_code == 400
    body1 = res1.json()
    err_msg1 = body1.get("error", {}).get("message") or body1.get("detail", "")
    assert "Both 'lat' and 'lon' query parameters must be provided" in err_msg1

    res2 = client.get("/api/opensky?lon=72.8777")
    assert res2.status_code == 400
    body2 = res2.json()
    err_msg2 = body2.get("error", {}).get("message") or body2.get("detail", "")
    assert "Both 'lat' and 'lon' query parameters must be provided" in err_msg2


def test_opensky_filter_by_callsign(client):
    """Filter by callsign returns only matching flights."""
    lat, lon = 19.076, 72.8777
    response = client.get(f"/api/opensky?lat={lat}&lon={lon}&callsign=FDX")
    assert response.status_code == 200
    data = response.json()
    assert data["meta"].get("filter_callsign") == "FDX"
    for vector in data["states"]:
        assert "FDX" in vector[1]


def test_opensky_filter_by_icao24(client):
    """Filter by icao24 hex code returns only matching flight."""
    lat, lon = 19.076, 72.8777
    response = client.get(f"/api/opensky?lat={lat}&lon={lon}&icao24=abe5a2")
    assert response.status_code == 200
    data = response.json()
    assert data["meta"].get("filter_icao24") == "abe5a2"
    for vector in data["states"]:
        assert vector[0].lower() == "abe5a2"


def test_flights_endpoint_alias(client):
    """GET /api/flights serves as an alias to GET /api/opensky."""
    response = client.get("/api/flights?lat=19.076&lon=72.8777")
    assert response.status_code == 200
    data = response.json()
    assert "states" in data
    assert len(data["states"]) > 0


def test_opensky_no_synthetic_injection_for_empty_airspace(client):
    """Verify that unpopulated coordinate regions return empty list and never inject synthetic flight data."""
    # Remote Antarctic coordinates far from any flights
    response = client.get("/api/opensky?lat=-85.0&lon=0.0&radius_nm=50.0")
    assert response.status_code == 200
    data = response.json()
    assert data["states"] == []
    assert data["meta"]["matched_record_count"] == 0
    assert data["meta"]["returned_record_count"] == 0
    assert data["meta"]["data_source_mode"] in ("GOVERNED_OPENSKY_DATASET", "LIVE_OPENSKY_NETWORK")


def test_geospatial_connector_opensky_ingestion():
    """Verify GeospatialConnectorAdapter successfully ingests OpenSky with GEV provenance."""
    connector = GeospatialConnectorAdapter()
    result = connector.ingest_gods_eye_view_source(gev_source_key="opensky", actor="test_operator")
    assert result["status"] == "SUCCESS"
    assert result["source"]["source_id"] == "src-gev-opensky"
    assert result["capability"]["capability_id"] in ("cap-gev-flight-tracking-staged", "cap-gev-flight-tracking")
    licensing = result["capability"].get("licensing") or result["capability"].get("licensing_metadata", {})
    assert licensing["dataset_licence"] == "OPEN_COMMUNITY_DATA_LICENSE"
    assert "OpenSky" in result["source"]["authority"]
    assert "gods-eye-view" in str(result["capability"]["provenance"])


def test_opensky_dataset_metadata_endpoint(client):
    """GET /api/datasets/ds-gev-opensky-flights returns exact dataset metadata and contracts."""
    response = client.get("/api/datasets/ds-gev-opensky-flights")
    assert response.status_code == 200
    data = response.json()
    assert data["dataset_id"] == "ds-gev-opensky-flights"
    assert data["file_location"] == "datasets/opensky_states.json"
    assert data["record_count"] == 17
    assert data["synthetic_records"] == 0
    assert data["associated_capability"]["capability_id"] == "cap-gev-flight-tracking-staged"
    assert data["associated_source"]["source_id"] == "src-gev-opensky"
    assert "ODbL" in data["licence"]["name"]
    assert data["provenance"]["synthetic"] is False


def test_opensky_dataset_records_endpoint(client):
    """GET /api/datasets/ds-gev-opensky-flights/records returns authentic OpenSky records."""
    response = client.get("/api/datasets/ds-gev-opensky-flights/records")
    assert response.status_code == 200
    data = response.json()
    assert "states" in data
    assert len(data["states"]) == 17
    assert data["meta"]["returned_record_count"] == 17


def test_core_dataset_endpoint_alias(client):
    """GET /datasets/ds-gev-opensky-flights resolves cleanly to the dataset definition."""
    response = client.get("/datasets/ds-gev-opensky-flights")
    assert response.status_code == 200
    data = response.json()
    assert data["dataset_id"] == "ds-gev-opensky-flights"
    assert data["record_count"] == 17
