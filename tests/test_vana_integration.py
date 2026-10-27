"""
Tests for MASTERDB ↔ VANA Forest & Mangrove Governance Integration.

Validates:
1. VanaClient contract methods, auth headers, and 6-tuple governance evaluation gate.
2. GeospatialConnectorAdapter.ingest_vana_source pipeline.
3. CapabilityRegistryService VANA governance gate evaluation and real data retrieval.
4. HTTP API capability discovery, contract resolution, access authorization, and retrieval.
"""
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from main import app
from models import (
    CapabilityAccessRequest,
    CapabilityRetrieveRequest,
    CapabilityStatus,
)
from services.capability_registry_service import (
    CapabilityAccessDeniedError,
    CapabilityRegistryService,
)
from services.vana_client import (
    VanaClient,
    VanaGovernanceDeniedError,
    VanaUnavailableError,
)
from integrations.geospatial_connector import GeospatialConnectorAdapter


client = TestClient(app)


def _get_token(actor="vana-tester", roles=None):
    res = client.post(
        "/auth/token",
        json={
            "actor": actor,
            "password": "test-auth-password",
            "roles": roles or ["ecosystem-reader"],
        },
    )
    assert res.status_code == 200
    return res.json()["access_token"]


# =============================================================================
# 1. VanaClient Unit Tests
# =============================================================================

def test_vana_client_unconfigured_raises():
    vc = VanaClient(base_url="")
    assert not vc.is_configured()
    with pytest.raises(VanaUnavailableError):
        vc.get_governed_datasets()


def test_vana_client_headers():
    vc = VanaClient(base_url="http://localhost:8001", api_key="test-api-key")
    assert vc.is_configured()
    headers = vc._headers()
    assert headers["X-API-Key"] == "test-api-key"
    assert headers["Content-Type"] == "application/json"


@patch("httpx.Client.post")
def test_vana_evaluate_governance_allowed(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "decision": "ALLOWED",
        "rule_codes": ["RULE-FSI-CANONICAL-OK"],
        "audit_trail": {"timestamp": "2026-10-15T12:00:00Z"},
    }
    mock_post.return_value = mock_resp

    vc = VanaClient(base_url="http://localhost:8001")
    res = vc.evaluate_governance(
        actor="MASTERDB",
        role="APPROVED_CONSUMER",
        dataset_id="DS-FSI-ISFR-2023-FOREST-COVER",
        action="READ",
        purpose="DISTRICT_CANOPY_ANALYSIS",
    )
    assert res["decision"] == "ALLOWED"
    assert "RULE-FSI-CANONICAL-OK" in res["rule_codes"]


@patch("httpx.Client.post")
def test_vana_evaluate_governance_denied(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "decision": "DENIED",
        "reason": "Actor lacks clearance for RESTRICTED dataset",
    }
    mock_post.return_value = mock_resp

    vc = VanaClient(base_url="http://localhost:8001")
    with pytest.raises(VanaGovernanceDeniedError) as exc_info:
        vc.evaluate_governance(
            actor="UNAUTHORIZED",
            role="GUEST",
            dataset_id="DS-FSI-ISFR-2023-FOREST-COVER",
            action="READ",
            purpose="UNAUTHORIZED_ANALYSIS",
        )
    assert "Actor lacks clearance" in str(exc_info.value)


@patch("httpx.Client.get")
def test_vana_data_retrieval_methods(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "ok", "records": [1, 2, 3]}
    mock_get.return_value = mock_resp

    vc = VanaClient(base_url="http://localhost:8001")
    
    assert vc.get_governed_datasets()["status"] == "ok"
    assert vc.get_real_observations()["status"] == "ok"
    assert vc.get_forest_cover_records()["status"] == "ok"
    assert vc.get_spatial_layers()["status"] == "ok"
    assert vc.get_spatial_geojson("thane_sanctuary")["status"] == "ok"
    assert vc.get_spatial_envelope()["status"] == "ok"
    assert vc.get_carbon_summary()["status"] == "ok"
    assert vc.get_carbon_maharashtra()["status"] == "ok"
    assert vc.get_carbon_thane_creek()["status"] == "ok"


# =============================================================================
# 2. GeospatialConnectorAdapter VANA Ingestion Tests
# =============================================================================

def test_geospatial_connector_ingest_vana_sources():
    connector = GeospatialConnectorAdapter()
    
    # Ingest forest cover
    res1 = connector.ingest_vana_source("forest_cover", actor="admin")
    assert res1["status"] == "SUCCESS"
    assert res1["capability"]["capability_id"] == "cap-vana-forest-cover"
    assert res1["capability"]["dataset_id"] == "DS-FSI-ISFR-2023-FOREST-COVER"

    # Ingest Thane Creek blue carbon
    res2 = connector.ingest_vana_source("thane_creek_carbon", actor="admin")
    assert res2["status"] == "SUCCESS"
    assert res2["capability"]["capability_id"] == "cap-vana-thane-creek-carbon"
    assert res2["capability"]["dataset_id"] == "DS-VANA-THANE-CREEK-BLUE-CARBON"

    # Ingest spatial layers
    res3 = connector.ingest_vana_source("spatial_layers", actor="admin")
    assert res3["status"] == "SUCCESS"
    assert res3["capability"]["capability_id"] == "cap-vana-spatial-layers"

    # Unknown source key error
    with pytest.raises(ValueError) as exc:
        connector.ingest_vana_source("invalid_key")
    assert "Unknown VANA source key" in str(exc.value)


# =============================================================================
# 3. CapabilityRegistryService VANA Governance & Retrieval Tests
# =============================================================================

def test_capability_registry_seeds_vana_capabilities():
    service = CapabilityRegistryService()
    cap = service.get_capability("cap-vana-forest-cover")
    assert cap.capability_id == "cap-vana-forest-cover"
    assert cap.domain == "geospatial"
    assert cap.required_purpose == "district_canopy_analysis"
    assert cap.status == CapabilityStatus.ACTIVE

    carbon_cap = service.get_capability("cap-vana-thane-creek-carbon")
    assert carbon_cap.capability_id == "cap-vana-thane-creek-carbon"
    assert carbon_cap.domain == "geospatial"
    assert carbon_cap.required_purpose == "carbon_quantification"


def test_capability_registry_vana_governance_denial_enforced():
    mock_vana = MagicMock(spec=VanaClient)
    mock_vana.is_configured.return_value = True
    mock_vana.evaluate_governance.side_effect = VanaGovernanceDeniedError("Policy violation: actor not approved")

    service = CapabilityRegistryService(vana_client=mock_vana)

    req = CapabilityAccessRequest(
        application_id="unauthorized-app",
        capability_id="cap-vana-forest-cover",
        purpose="district_canopy_analysis",
    )
    with pytest.raises(CapabilityAccessDeniedError) as exc:
        service.request_access(actor="test-actor", roles=["ecosystem-reader"], request_data=req)
    assert "VANA 6-tuple governance evaluation denied access" in str(exc.value)


def test_capability_registry_vana_live_retrieval_when_configured():
    mock_vana = MagicMock(spec=VanaClient)
    mock_vana.is_configured.return_value = True
    mock_vana.evaluate_governance.return_value = {"decision": "ALLOWED"}
    mock_vana.get_forest_cover_records.return_value = {
        "dataset_id": "DS-FSI-ISFR-2023-FOREST-COVER",
        "live_records": [{"district": "Thane", "canopy_density": 82.4}],
        "source": "VANA Production Backend",
    }

    service = CapabilityRegistryService(vana_client=mock_vana)

    ret_req = CapabilityRetrieveRequest(
        application_id="masterdb-consumer",
        purpose="district_canopy_analysis",
    )
    response = service.retrieve(
        actor="masterdb-consumer",
        roles=["ecosystem-reader"],
        capability_id="cap-vana-forest-cover",
        retrieve_req=ret_req,
    )
    assert response.data["source"] == "VANA Production Backend"
    assert response.data["live_records"][0]["district"] == "Thane"
    assert response.capability["capability_id"] == "cap-vana-forest-cover"


def test_capability_registry_vana_fallback_when_unconfigured():
    # When unconfigured, should return structured canonical domain payload
    unconfigured_vana = VanaClient(base_url="")
    service = CapabilityRegistryService(vana_client=unconfigured_vana)

    ret_req = CapabilityRetrieveRequest(
        application_id="masterdb-consumer",
        purpose="district_canopy_analysis",
    )
    response = service.retrieve(
        actor="masterdb-consumer",
        roles=["ecosystem-reader"],
        capability_id="cap-vana-forest-cover",
        retrieve_req=ret_req,
    )
    assert response.data["dataset_id"] == "DS-FSI-ISFR-2023-FOREST-COVER"
    assert response.data["governance_status"] == "CANONICAL_ISFR_2023"
    assert len(response.data["records"]) >= 1


# =============================================================================
# 4. HTTP API End-to-End Tests
# =============================================================================

def test_http_api_vana_discovery_and_contract():
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}

    # Discovery
    res = client.get("/capabilities/cap-vana-forest-cover", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["capability_id"] == "cap-vana-forest-cover"
    assert data["dataset_id"] == "DS-FSI-ISFR-2023-FOREST-COVER"

    # Contract
    res = client.get("/capabilities/cap-vana-forest-cover/contract", headers=headers)
    assert res.status_code == 200
    contract = res.json()
    assert contract["capability_id"] == "cap-vana-forest-cover"
    assert contract["required_purpose"] == "district_canopy_analysis"


def test_http_api_vana_access_request_and_retrieve():
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}

    # Request Access
    access_req = {
        "application_id": "vana-tester",
        "capability_id": "cap-vana-forest-cover",
        "purpose": "district_canopy_analysis",
    }
    res = client.post("/access/request", json=access_req, headers=headers)
    assert res.status_code == 200
    access_token = res.json()["access_token"]
    assert access_token is not None

    # Retrieve Data
    ret_req = {
        "application_id": "vana-tester",
        "access_token": access_token,
    }
    res = client.post("/capabilities/cap-vana-forest-cover/retrieve", json=ret_req, headers=headers)
    assert res.status_code == 200
    ret_data = res.json()
    assert ret_data["capability"]["capability_id"] == "cap-vana-forest-cover"
    assert "data" in ret_data
