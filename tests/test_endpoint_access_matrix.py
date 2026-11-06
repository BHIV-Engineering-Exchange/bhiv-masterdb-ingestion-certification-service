"""
Endpoint Access Matrix & Governance Verification Test Suite (F-07 / D1 Closure).

Verifies the 4-tier security classification across all MASTERDB endpoints:
1. PUBLIC: Freely accessible without authentication (HTTP 200).
2. AUTHENTICATED: Requires valid Bearer JWT; returns HTTP 401 when unauthenticated.
3. AUTHORIZED / INTERNAL:
   - Returns HTTP 401 when unauthenticated.
   - Returns HTTP 403 when authenticated caller lacks required role (e.g. viewer role).
   - Authorizes execution for callers with operator or bhiv-admin role.
   - Binds actor attribution strictly to verified token identity (ignoring caller body actor).
"""
import pytest
from fastapi.testclient import TestClient

import main
from auth.constants import ADMIN_ROLE
from auth.models import AuthIdentity
from tests.identity_fixtures import get_test_auth_headers, get_test_token


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


@pytest.fixture
def viewer_headers() -> dict:
    return get_test_auth_headers(actor="test-viewer", roles=["viewer", "ecosystem-reader"])


@pytest.fixture
def operator_headers() -> dict:
    return get_test_auth_headers(actor="test-operator", roles=["operator", "ingest:operator"])


@pytest.fixture
def admin_headers() -> dict:
    return get_test_auth_headers(actor="test-admin", roles=[ADMIN_ROLE, "operator"])


# =============================================================================
# 1. PUBLIC ENDPOINTS (Intentionally unauthenticated -> HTTP 200)
# =============================================================================

@pytest.mark.parametrize(
    "path",
    [
        "/health",
        "/ready",
        "/runtime/identity",
        "/metrics",
        "/docs",
        "/openapi.json",
        "/earthquakes/map",
        "/live-datasets/registry",
    ],
)
def test_public_endpoints_accessible_without_auth(client: TestClient, path: str):
    response = client.get(path)
    assert response.status_code == 200, f"Expected 200 for public route {path}, got {response.status_code}: {response.text}"


# =============================================================================
# 2. 13 CRITICAL MUTATION ROUTES (Unauthenticated -> HTTP 401)
# =============================================================================

@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("POST", "/packages/register", {"dataset_id": "ds-sec-1", "dataset_version": "1.0.0", "schema_version": "1", "board": "test", "medium": "test", "language": "en", "owner": "test"}),
        ("POST", "/packages/promote", {"package_id": "pkg-sec-1", "to_status": "INGESTED", "reason": "test"}),
        ("POST", "/packages/deprecate", {"package_id": "pkg-sec-1", "reason": "test"}),
        ("POST", "/packages/pkg-sec-1/knowledge-object", {"package_id": "pkg-sec-1"}),
        ("POST", "/tantra/datasets/register", {"dataset_id": "ds-sec-2", "dataset_version": "1.0.0", "schema_version": "1", "board": "test", "medium": "test", "language": "en", "owner": "test"}),
        ("POST", "/validate", {"dataset_id": "ds-sec-val", "dataset_path": "path", "metadata_path": "mpath"}),
        ("POST", "/certify", {"dataset_id": "ds-sec-cert", "dataset_path": "path", "metadata_path": "mpath"}),
        ("POST", "/shared/parikshak/register", {"record_id": "rec-1", "payload": {"foo": "bar"}}),
        ("PUT", "/shared/parikshak/rec-1", {"payload": {"foo": "bar"}}),
        ("POST", "/shared/parikshak/rec-1/deprecate", {"reason": "test"}),
        ("POST", "/pravah/events", {"event_id": "evt-1", "topic": "pkg.events", "event_type": "PACKAGE_REGISTERED", "entity_type": "PACKAGE", "entity_id": "pkg-1", "producer": "test", "target_status": "REGISTERED", "timestamp": "2026-11-03T12:00:00Z"}),
        ("POST", "/pravah/replay", {"from_sequence": 1, "to_sequence": 2}),
        ("POST", "/pipeline/execute", {"entity_id": "pkg-test", "entity_type": "PACKAGE", "initial_status": "REGISTERED", "target_status": "INGESTED", "actor": "spoofed"}),
    ],
)
def test_13_mutation_routes_reject_unauthenticated_with_401(client: TestClient, method: str, path: str, payload: dict):
    if method == "POST":
        response = client.post(path, json=payload)
    elif method == "PUT":
        response = client.put(path, json=payload)
    assert response.status_code == 401, f"Expected 401 for {method} {path}, got {response.status_code}: {response.text}"


# =============================================================================
# 3. 13 CRITICAL MUTATION ROUTES (Viewer Role -> HTTP 403)
# =============================================================================

@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("POST", "/packages/register", {"dataset_id": "ds-sec-1", "dataset_version": "1.0.0", "schema_version": "1", "board": "test", "medium": "test", "language": "en", "owner": "test"}),
        ("POST", "/packages/promote", {"package_id": "pkg-sec-1", "to_status": "INGESTED", "reason": "test"}),
        ("POST", "/packages/deprecate", {"package_id": "pkg-sec-1", "reason": "test"}),
        ("POST", "/packages/pkg-sec-1/knowledge-object", {"package_id": "pkg-sec-1"}),
        ("POST", "/tantra/datasets/register", {"dataset_id": "ds-sec-2", "dataset_version": "1.0.0", "schema_version": "1", "board": "test", "medium": "test", "language": "en", "owner": "test"}),
        ("POST", "/validate", {"dataset_id": "ds-sec-val", "dataset_path": "path", "metadata_path": "mpath"}),
        ("POST", "/certify", {"dataset_id": "ds-sec-cert", "dataset_path": "path", "metadata_path": "mpath"}),
        ("POST", "/shared/parikshak/register", {"record_id": "rec-1", "payload": {"foo": "bar"}}),
        ("PUT", "/shared/parikshak/rec-1", {"payload": {"foo": "bar"}}),
        ("POST", "/shared/parikshak/rec-1/deprecate", {"reason": "test"}),
        ("POST", "/pravah/events", {"event_id": "evt-1", "topic": "pkg.events", "event_type": "PACKAGE_REGISTERED", "entity_type": "PACKAGE", "entity_id": "pkg-1", "producer": "test", "target_status": "REGISTERED", "timestamp": "2026-11-03T12:00:00Z"}),
        ("POST", "/pravah/replay", {"from_sequence": 1, "to_sequence": 2}),
        ("POST", "/pipeline/execute", {"entity_id": "pkg-test", "entity_type": "PACKAGE", "initial_status": "REGISTERED", "target_status": "INGESTED", "actor": "spoofed"}),
    ],
)
def test_13_mutation_routes_reject_viewer_with_403(client: TestClient, viewer_headers: dict, method: str, path: str, payload: dict):
    if method == "POST":
        response = client.post(path, json=payload, headers=viewer_headers)
    elif method == "PUT":
        response = client.put(path, json=payload, headers=viewer_headers)
    assert response.status_code == 403, f"Expected 403 for viewer on {method} {path}, got {response.status_code}: {response.text}"


# =============================================================================
# 4. OBSERVATION INGEST & VERIFY ROUTES (Viewer -> 403; Unauthenticated -> 401)
# =============================================================================

@pytest.mark.parametrize(
    "path,payload",
    [
        ("/connectors/geospatial/ingest", {"source_id": "src-test", "data": {}}),
        ("/earthquakes/usgs/ingest", {}),
        ("/aisstream/ingest", {"positions": []}),
        ("/aircraft/adsb/military/ingest", {}),
        ("/wildfires/firms/ingest", {}),
        ("/traffic/tomtom/ingest", {"traffic": {}}),
        ("/weather/wind/gfs/ingest", {"forecast": {}}),
        ("/weather/open-meteo/ingest", {"weather": {}}),
        ("/weather/radar/verify", {}),
        ("/weather/lightning/verify", {}),
        ("/cyclones/nhc/ingest", {}),
        ("/weather/satellite/verify?product=clouds", {}),
        ("/natural-earth/countries/ingest", {}),
        ("/dams/ingest", {}),
        ("/events/bhote-koshi/ingest", {}),
        ("/geospatial/3d-tiles/photorealistic/verify", {}),
        ("/geospatial/satellite-imagery/verify", {}),
        ("/geospatial/terrain/verify", {}),
        ("/geospatial/vector-basemap/verify", {}),
    ],
)
def test_observation_ingests_reject_unauthenticated_and_viewers(client: TestClient, viewer_headers: dict, path: str, payload: dict):
    # Unauthenticated -> 401
    unauth_resp = client.post(path, json=payload)
    assert unauth_resp.status_code == 401, f"Expected 401 for unauthenticated on {path}, got {unauth_resp.status_code}"

    # Viewer -> 403
    viewer_resp = client.post(path, json=payload, headers=viewer_headers)
    assert viewer_resp.status_code == 403, f"Expected 403 for viewer on {path}, got {viewer_resp.status_code}"


# =============================================================================
# 5. RETRIEVAL ROUTES (Unauthenticated -> 401)
# =============================================================================

@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("POST", "/query", {"dataset_id": "ds-1", "query_params": {}}),
        ("POST", "/export", {"dataset_id": "ds-1", "format": "csv"}),
        ("POST", "/stream", {"dataset_id": "ds-1", "stream_params": {}}),
        ("POST", "/reference", {"dataset_id": "ds-1"}),
        ("GET", "/tantra/packages/pkg-test/runtime", None),
        ("GET", "/api/opensky", None),
        ("GET", "/api/flights", None),
        ("GET", "/api/datasets/ds-gev-opensky-flights", None),
        ("GET", "/datasets/ds-gev-opensky-flights", None),
        ("GET", "/api/datasets/ds-gev-opensky-flights/records", None),
        ("GET", "/datasets", None),
        ("GET", "/datasets/ds-1", None),
        ("GET", "/packages/pkg-1", None),
        ("GET", "/discovery/packages", None),
    ],
)
def test_retrieval_routes_reject_unauthenticated_with_401(client: TestClient, method: str, path: str, payload: dict):
    if method == "POST":
        response = client.post(path, json=payload)
    else:
        response = client.get(path)
    assert response.status_code == 401, f"Expected 401 for {method} {path}, got {response.status_code}"


# =============================================================================
# 6. ACTOR ATTRIBUTION BINDING (Token Identity Binds; Body Actor Ignored)
# =============================================================================

def test_package_registration_binds_actor_to_verified_identity(client: TestClient, operator_headers: dict):
    """
    Assert that when caller provides body 'actor: spoofed-attacker', the registry
    records 'actor: test-operator' as derived strictly from the verified JWT.
    """
    payload = {
        "dataset_id": "ds-governed-attr-1",
        "dataset_version": "1.0.0",
        "schema_version": "1.0",
        "board": "AI",
        "medium": "text",
        "language": "en",
        "owner": "kavy",
        "actor": "spoofed-attacker",  # Adversary attempts to attribute registration to someone else
        "reason": "Security attribution test",
    }
    response = client.post("/packages/register", json=payload, headers=operator_headers)
    assert response.status_code == 200, f"Registration failed: {response.text}"
    body = response.json()
    package_id = body["package_id"]
    
    # Assert package records verified operator actor in its transition history, not the spoofed body actor
    assert body["history"][0]["actor"] == "test-operator", f"Actor was not bound to verified identity: {body['history'][0]['actor']}"
    
    # Verify in history
    history = main.package_registry_service.history(package_id)
    assert len(history) > 0
    assert history[0].actor == "test-operator", f"History actor was not bound: {history[0].actor}"
