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
import httpx
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
    import os
    res = client.post(
        "/auth/token",
        json={
            "actor": actor,
            "password": os.environ.get("AUTH_PASSWORD", "test-auth-password"),
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

    vc = VanaClient(base_url="http://localhost:8001", api_key="test-api-key")
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

    vc = VanaClient(base_url="http://localhost:8001", api_key="test-api-key")
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

    vc = VanaClient(base_url="http://localhost:8001", api_key="test-api-key")
    
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
    """Under D3 fail-closed governance, accessing a VANA-governed capability without VANA configured raises VanaUnavailableError."""
    unconfigured_vana = VanaClient(base_url="")
    service = CapabilityRegistryService(vana_client=unconfigured_vana)

    ret_req = CapabilityRetrieveRequest(
        application_id="masterdb-consumer",
        purpose="district_canopy_analysis",
    )
    with pytest.raises(VanaUnavailableError) as exc_info:
        service.retrieve(
            actor="masterdb-consumer",
            roles=["ecosystem-reader"],
            capability_id="cap-vana-forest-cover",
            retrieve_req=ret_req,
        )
    assert "not configured" in str(exc_info.value).lower()


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

    # When VANA is configured and grants ALLOWED, access and retrieval succeed
    with patch.object(VanaClient, "is_configured", return_value=True), \
         patch.object(VanaClient, "evaluate_governance", return_value={"decision": "ALLOWED"}):
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


# =============================================================================
# 5. D3 & D6 Fail-Closed Governance & Credential Hygiene Regression Tests
# =============================================================================

def test_credential_hygiene_missing_api_key_unconfigured():
    """D6: When VANA_API_KEY is missing or empty, is_configured() must return False."""
    vc = VanaClient(base_url="http://localhost:8001", api_key="")
    assert not vc.is_configured()

    with patch.dict("os.environ", {}, clear=True):
        vc_clean = VanaClient(base_url="http://localhost:8001", api_key=None)
        assert not vc_clean.is_configured()
        assert vc_clean.api_key == ""


@pytest.mark.parametrize("decision", ["PENDING", "UNKNOWN", "FLAGGED", "CONTROLLED", "REQUIRES_APPROVAL", ""])
@patch("httpx.Client.post")
def test_vana_evaluate_governance_non_allowed_decisions_fail_closed(mock_post, decision):
    """D3: Any decision other than explicit ALLOWED raises VanaGovernanceDeniedError."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"decision": decision, "reason": f"Status is {decision}"}
    mock_post.return_value = mock_resp

    vc = VanaClient(base_url="http://localhost:8001", api_key="test-api-key")
    with pytest.raises(VanaGovernanceDeniedError) as exc_info:
        vc.evaluate_governance(
            actor="MASTERDB",
            role="APPROVED_CONSUMER",
            dataset_id="DS-FSI-ISFR-2023-FOREST-COVER",
            action="READ",
            purpose="DISTRICT_CANOPY_ANALYSIS",
        )
    assert "not permitted by VANA governance policy" in str(exc_info.value) or f"Status is {decision}" in str(exc_info.value)


@patch("httpx.Client.post", side_effect=httpx.ConnectTimeout("Connection timed out to VANA"))
def test_vana_evaluate_governance_timeout_raises_unavailable(mock_post):
    """D3: Network timeout calling VANA raises VanaUnavailableError."""
    vc = VanaClient(base_url="http://localhost:8001", api_key="test-api-key")
    with pytest.raises(VanaUnavailableError) as exc_info:
        vc.evaluate_governance(
            actor="MASTERDB",
            role="APPROVED_CONSUMER",
            dataset_id="DS-FSI-ISFR-2023-FOREST-COVER",
            action="READ",
            purpose="DISTRICT_CANOPY_ANALYSIS",
        )
    assert "failed" in str(exc_info.value).lower()


@patch("httpx.Client.post", side_effect=httpx.ConnectError("Connection refused by VANA host"))
def test_vana_evaluate_governance_connect_error_raises_unavailable(mock_post):
    """D3: Connection refused calling VANA raises VanaUnavailableError."""
    vc = VanaClient(base_url="http://localhost:8001", api_key="test-api-key")
    with pytest.raises(VanaUnavailableError) as exc_info:
        vc.evaluate_governance(
            actor="MASTERDB",
            role="APPROVED_CONSUMER",
            dataset_id="DS-FSI-ISFR-2023-FOREST-COVER",
            action="READ",
            purpose="DISTRICT_CANOPY_ANALYSIS",
        )
    assert "failed" in str(exc_info.value).lower()


@patch("httpx.Client.post")
def test_vana_evaluate_governance_http_500_raises_unavailable(mock_post):
    """D3: HTTP 500 error from VANA raises VanaUnavailableError."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("500 Internal Server Error", request=MagicMock(), response=mock_resp)
    mock_post.return_value = mock_resp

    vc = VanaClient(base_url="http://localhost:8001", api_key="test-api-key")
    with pytest.raises(VanaUnavailableError) as exc_info:
        vc.evaluate_governance(
            actor="MASTERDB",
            role="APPROVED_CONSUMER",
            dataset_id="DS-FSI-ISFR-2023-FOREST-COVER",
            action="READ",
            purpose="DISTRICT_CANOPY_ANALYSIS",
        )
    assert "failed" in str(exc_info.value).lower()


def test_capability_registry_unconfigured_vana_denies_governed_capability_and_audits():
    """D3 & D6: Unconfigured VANA client on governed capability raises VanaUnavailableError, audits failure, and creates no contract."""
    unconfigured_vana = VanaClient(base_url="", api_key="")
    service = CapabilityRegistryService(vana_client=unconfigured_vana)

    initial_contracts_count = len(service._access_contracts)
    req = CapabilityAccessRequest(
        application_id="consumer-app",
        capability_id="cap-vana-forest-cover",
        purpose="district_canopy_analysis",
    )
    with pytest.raises(VanaUnavailableError) as exc_info:
        service.request_access(actor="test-actor", roles=["ecosystem-reader"], request_data=req)
    assert "not configured" in str(exc_info.value)

    # Verify no contract was created
    assert len(service._access_contracts) == initial_contracts_count

    # Verify audit record created with result="DENIED"
    audits = service.audit_emitter.get_chain()
    denial_audits = [
        e for e in audits
        if e.payload.get("action") == "ACCESS_REQUEST"
        and e.payload.get("result") == "DENIED"
        and e.payload.get("capability_id") == "cap-vana-forest-cover"
        and e.actor == "test-actor"
    ]
    assert len(denial_audits) >= 1
    assert "not configured" in denial_audits[-1].payload["reason"]


@pytest.mark.parametrize("decision", ["PENDING", "UNKNOWN", "FLAGGED", "CONTROLLED"])
def test_capability_registry_unexpected_decision_denies_governed_capability(decision):
    """D3: Unexpected decision from VANA raises CapabilityAccessDeniedError and creates no contract."""
    mock_vana = MagicMock(spec=VanaClient)
    mock_vana.is_configured.return_value = True
    mock_vana.evaluate_governance.side_effect = VanaGovernanceDeniedError(f"Access not permitted by VANA governance policy (decision: {decision}).")

    service = CapabilityRegistryService(vana_client=mock_vana)
    initial_contracts_count = len(service._access_contracts)

    req = CapabilityAccessRequest(
        application_id="consumer-app",
        capability_id="cap-vana-forest-cover",
        purpose="district_canopy_analysis",
    )
    with pytest.raises(CapabilityAccessDeniedError) as exc_info:
        service.request_access(actor="test-actor", roles=["ecosystem-reader"], request_data=req)
    assert "VANA 6-tuple governance evaluation denied access" in str(exc_info.value)
    assert len(service._access_contracts) == initial_contracts_count


def test_capability_registry_timeout_or_error_denies_governed_capability():
    """D3: VANA timeout or error raises VanaUnavailableError and creates no contract."""
    mock_vana = MagicMock(spec=VanaClient)
    mock_vana.is_configured.return_value = True
    mock_vana.evaluate_governance.side_effect = VanaUnavailableError("VANA call to /api/v1/governance/evaluate timed out")

    service = CapabilityRegistryService(vana_client=mock_vana)
    initial_contracts_count = len(service._access_contracts)

    req = CapabilityAccessRequest(
        application_id="consumer-app",
        capability_id="cap-vana-forest-cover",
        purpose="district_canopy_analysis",
    )
    with pytest.raises(VanaUnavailableError) as exc_info:
        service.request_access(actor="test-actor", roles=["ecosystem-reader"], request_data=req)
    assert "unavailable" in str(exc_info.value).lower()
    assert len(service._access_contracts) == initial_contracts_count

    # Check audit record
    audits = service.audit_emitter.get_chain()
    denial_audits = [
        e for e in audits
        if e.payload.get("action") == "ACCESS_REQUEST"
        and e.payload.get("result") == "DENIED"
        and e.payload.get("capability_id") == "cap-vana-forest-cover"
    ]
    assert len(denial_audits) >= 1


def test_capability_registry_non_governed_capability_unaffected_when_vana_unconfigured_or_down():
    """D3: Non-governed capabilities (e.g. cap-mangrove-monitoring) succeed even if VANA is unconfigured or down."""
    mock_vana = MagicMock(spec=VanaClient)
    mock_vana.is_configured.return_value = False
    mock_vana.evaluate_governance.side_effect = RuntimeError("VANA is completely down")

    service = CapabilityRegistryService(vana_client=mock_vana)

    # cap-mangrove-monitoring has dataset DS-MANGROVE-CANOPY-2024 (not DS-FSI- or DS-VANA-)
    req = CapabilityAccessRequest(
        application_id="marine-consumer",
        capability_id="cap-mangrove-monitoring",
        purpose="environmental_monitoring",
    )
    contract = service.request_access(actor="marine-analyst", roles=["ecosystem-reader"], request_data=req)
    assert contract.authorized is True
    assert contract.capability_id == "cap-mangrove-monitoring"
    assert contract.access_token is not None


def test_http_api_governed_capability_unconfigured_returns_503():
    """D3 & D6: When VANA is unconfigured, HTTP access request for governed capability returns HTTP 503."""
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}

    access_req = {
        "application_id": "vana-tester",
        "capability_id": "cap-vana-forest-cover",
        "purpose": "district_canopy_analysis",
    }
    with patch.object(VanaClient, "is_configured", return_value=False):
        res = client.post("/access/request", json=access_req, headers=headers)
        assert res.status_code == 503
        err_msg = res.json().get("detail") or res.json().get("error", {}).get("message", "")
        assert "not configured" in err_msg.lower()


def test_http_api_governed_capability_denied_returns_403():
    """D3: When VANA denies governance evaluation, HTTP access request returns HTTP 403."""
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}

    access_req = {
        "application_id": "vana-tester",
        "capability_id": "cap-vana-forest-cover",
        "purpose": "district_canopy_analysis",
    }
    with patch.object(VanaClient, "is_configured", return_value=True),          patch.object(VanaClient, "evaluate_governance", side_effect=VanaGovernanceDeniedError("Clearance revoked")):
        res = client.post("/access/request", json=access_req, headers=headers)
        assert res.status_code == 403
        err_msg = res.json().get("detail") or res.json().get("error", {}).get("message", "")
        assert "denied" in err_msg.lower()


def test_http_api_governed_capability_unavailable_returns_503():
    """D3: When VANA encounters network failure/timeout, HTTP access request returns HTTP 503."""
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}

    access_req = {
        "application_id": "vana-tester",
        "capability_id": "cap-vana-forest-cover",
        "purpose": "district_canopy_analysis",
    }
    with patch.object(VanaClient, "is_configured", return_value=True),          patch.object(VanaClient, "evaluate_governance", side_effect=VanaUnavailableError("VANA connection timeout")):
        res = client.post("/access/request", json=access_req, headers=headers)
        assert res.status_code == 503
        err_msg = res.json().get("detail") or res.json().get("error", {}).get("message", "")
        assert "timeout" in err_msg.lower()
