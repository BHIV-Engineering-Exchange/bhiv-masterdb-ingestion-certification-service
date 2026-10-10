import uuid
import pytest
from fastapi.testclient import TestClient

from main import app
from services.masterdb_test_consumer import MasterDBTestConsumer


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_header(client):
    res = client.post("/auth/token", json={"actor": "geo-quest-tester", "roles": ["ecosystem-reader", "viewer", "operator", "admin"]})
    assert res.status_code == 200
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_source_registration_and_duplicate_detection(client, auth_header):
    src_id = f"src-isro-sentinel-{uuid.uuid4().hex[:8]}"
    # Register source with write authority confirmed
    payload = {
        "source_id": src_id,
        "name": f"ISRO Sentinel Optical Constellation {src_id}",
        "authority": "National Remote Sensing Centre",
        "source_type": "SATELLITE",
        "licence": "OPEN_DATA",
        "access_method": "REST_API",
        "geographic_coverage": "INDIA_PAN",
        "update_characteristics": "5_DAY_REVISIT",
        "reliability_limitations": "CLOUD_COVER",
        "attribution": "ISRO / NRSC Data Engine",
        "connector": "isro_sentinel_connector",
        "confirm_write_authority": True,
    }
    res = client.post("/sources/register", json=payload, headers=auth_header)
    assert res.status_code == 201
    data = res.json()
    assert data["source_id"] == src_id
    assert data["status"] == "ACTIVE"
    assert data["write_authority_confirmed"] is True

    # Attempt duplicate registration -> HTTP 409
    res_dup = client.post("/sources/register", json=payload, headers=auth_header)
    assert res_dup.status_code == 409
    assert "already exists" in res_dup.json()["error"]["message"]


def test_source_registration_unconfirmed_authority(client, auth_header):
    src_id = f"src-unconfirmed-{uuid.uuid4().hex[:8]}"
    payload = {
        "source_id": src_id,
        "name": f"Unconfirmed External Survey Source {src_id}",
        "confirm_write_authority": False,
    }
    res = client.post("/sources/register", json=payload, headers=auth_header)
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "PENDING AUTHORITY CONFIRMATION"
    assert data["authority"] == "NOT VERIFIED"
    assert data["licence"] == "PENDING"
    assert data["geographic_coverage"] == "UNKNOWN"
    assert data["write_authority_confirmed"] is False



def test_capability_discovery_and_contract(client, auth_header):
    # Discovery
    res = client.get("/capabilities?domain=geospatial", headers=auth_header)
    assert res.status_code == 200
    capabilities = res.json()
    assert len(capabilities) >= 1
    cap = capabilities[0]
    assert cap["domain"] == "geospatial"

    # Contract retrieval
    cap_id = cap["capability_id"]
    res_contract = client.get(f"/capabilities/{cap_id}/contract", headers=auth_header)
    assert res_contract.status_code == 200
    contract = res_contract.json()
    assert contract["capability_id"] == cap_id
    assert "access_endpoint" in contract
    assert "licensing_metadata" in contract
    assert "inputs" in contract
    assert "outputs" in contract


def test_capability_registration_requires_admin(client, auth_header):
    cap_payload = {
        "capability_id": "cap-mangrove-monitoring",
        "capability_name": "Duplicate Mangrove Capability",
        "description": "Attempt to overwrite",
        "dataset_id": "ds-mangrove-001",
        "registration_authority_confirmed": True,
    }
    unauthenticated = client.post(
        "/capabilities/register",
        json=cap_payload,
        headers={"Authorization": f"******"},
    )
    assert unauthenticated.status_code == 401
    res = client.post("/capabilities/register", json=cap_payload, headers=auth_header)
    assert res.status_code == 403


def test_capability_access_and_retrieval_flow(client, auth_header):
    cap_id = "cap-mangrove-monitoring"

    # Request access grant
    access_req = {
        "application_id": "BHARAT_MALA_ENV",
        "capability_id": cap_id,
        "purpose": "environmental_monitoring",
    }
    res_access = client.post("/access/request", json=access_req, headers=auth_header)
    assert res_access.status_code == 200
    grant = res_access.json()
    assert grant["authorized"] is True
    token = grant["access_token"]

    # Governed retrieval
    retrieve_req = {
        "application_id": "BHARAT_MALA_ENV",
        "access_token": token,
        "query_params": {"region": "Sundarbans-Delta"},
    }
    res_ret = client.post(f"/capabilities/{cap_id}/retrieve", json=retrieve_req, headers=auth_header)
    assert res_ret.status_code == 200
    body = res_ret.json()
    assert body["capability"]["capability_id"] == cap_id
    assert body["access_metadata"]["authorization_status"] == "AUTHORIZED"
    assert "provenance" in body
    assert body["data"]["region"] == "Sundarbans-Delta"


def test_geospatial_connector_pipeline(client, auth_header):
    connector_payload = {
        "source_id": "src-isro-cartosat-009",
        "source_name": "ISRO Cartosat High Resolution Terrain",
        "authority": "ISRO NRSC",
        "licence": "GOVT_STRICT",
        "geographic_coverage": "HIMALAYAN_CORRIDOR",
        "dataset_id": "ds-cartosat-himalaya",
        "capability_id": "cap-terrain-change-detection",
        "capability_name": "Himalayan Landslide & Terrain Change Detection",
        "description": "Satellite optical and DEM change detection for highway corridor safety",
        "confirm_write_authority": True,
    }

    res = client.post("/connectors/geospatial/ingest", json=connector_payload, headers=auth_header)
    assert res.status_code == 200
    out = res.json()
    assert out["status"] == "SUCCESS"
    assert out["source"]["source_id"] == "src-isro-cartosat-009"
    assert out["capability"]["capability_id"] == "cap-terrain-change-detection"
    assert out["pipeline"] == "EXTERNAL_SOURCE -> CONNECTOR -> VALIDATION -> MDU -> MASTERDB -> CAPABILITY"


def test_unauthorized_access_rejection(client):
    # Unauthenticated request -> HTTP 401
    res = client.get("/capabilities")
    assert res.status_code == 401


def test_masterdb_test_consumer_multi_consumer_flow(client):
    test_consumer = MasterDBTestConsumer(client=client)
    res = test_consumer.run_multi_consumer_demonstration()
    assert res["status"] == "SUCCESS"
    assert res["consumers_tested"] == 3
    assert res["shared_contract_verified"] is True
    assert "BHARAT_MALA_APP" in res["results"]
    assert "VANA_FIN_APP" in res["results"]
    assert "MARINE_INTEL_APP" in res["results"]


def test_marine_intel_and_license_safe_capabilities(client, auth_header):
    # Discovery of approved capabilities (excluding restricted OpenSky)
    res = client.get("/capabilities", headers=auth_header)
    assert res.status_code == 200
    caps = res.json()
    cap_ids = [c["capability_id"] for c in caps]
    assert "cap-marine-intel-ports" in cap_ids
    assert "cap-gev-satellite-pass-prediction" in cap_ids
    assert "cap-gev-wildfire-perimeter-monitoring" in cap_ids
    assert "cap-gev-weather-forecast-tracking" in cap_ids
    assert "cap-gev-earthquake-monitoring" in cap_ids
    assert "cap-gev-flight-tracking" not in cap_ids

    # Check Marine Intel Ports capability contract
    cap_id = "cap-marine-intel-ports"
    res_contract = client.get(f"/capabilities/{cap_id}/contract", headers=auth_header)
    assert res_contract.status_code == 200
    contract = res_contract.json()
    assert contract["capability_id"] == cap_id
    assert contract["source_id"] == "src-marine-intel-ports"
    assert contract["dataset_id"] == "ds-marine-intel-ports"
    assert contract["licensing_metadata"]["software_licence"] == "MIT"
    assert contract["licensing_metadata"]["dataset_licence"] == "PUBLIC_GOVERNMENT_DATA"

    # Governed access flow for Marine Intel Ports
    res_grant = client.post("/access/request", json={
        "application_id": "MARINE_INTELLIGENCE_APP",
        "capability_id": cap_id,
        "purpose": "maritime_infrastructure_analytics",
    }, headers=auth_header)
    assert res_grant.status_code == 200
    grant_token = res_grant.json()["access_token"]

    res_ret = client.post(f"/capabilities/{cap_id}/retrieve", json={
        "application_id": "MARINE_INTELLIGENCE_APP",
        "access_token": grant_token,
        "query_params": {"port_type": "Major Port"},
    }, headers=auth_header)
    assert res_ret.status_code == 200
    ret_data = res_ret.json()
    assert ret_data["capability"]["capability_id"] == cap_id
    assert ret_data["provenance"]["repository"] == "https://github.com/shravani2207-tech/marine-intelligence-task"
    assert ret_data["provenance"]["commit"] == "03af9e32eeba275592a8e19041d7b51d6139dad7"


def test_restricted_source_registration_rejection(client, auth_header):
    # Attempting to register OpenSky source -> raises error / 400 Bad Request
    payload = {
        "source_id": "src-opensky-test",
        "name": "OpenSky Network Test Source",
        "authority": "Unverified OpenSky",
        "confirm_write_authority": True,
    }
    res = client.post("/sources/register", json=payload, headers=auth_header)
    assert res.status_code == 400
    assert "prohibited" in res.json()["error"]["message"]


def test_license_safe_connector_ingestion(client, auth_header):
    from integrations.geospatial_connector import GeospatialConnectorAdapter

    connector = GeospatialConnectorAdapter()
    result = connector.ingest_gods_eye_view_source(gev_source_key="marine_ports", actor="test_runner")
    assert result["status"] == "SUCCESS"
    assert result["source"]["source_id"] == "src-marine-intel-ports"
    assert result["capability"]["capability_id"] == "cap-marine-intel-ports"
    assert result["pipeline"] == "EXTERNAL_SOURCE -> CONNECTOR -> VALIDATION -> MDU -> MASTERDB -> CAPABILITY"
