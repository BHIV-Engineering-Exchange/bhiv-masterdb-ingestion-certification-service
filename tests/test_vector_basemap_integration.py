import json

from fastapi.testclient import TestClient

import main
from auth.models import AuthIdentity
from integrations import gods_eye_view_vector_basemap_connector as connector
from services.source_registry_service import SourceRegistryService


def test_vector_basemap_manifest_uses_confirmed_openfreemap_metadata():
    manifest = connector.safe_manifest()
    serialized = json.dumps(manifest)
    assert manifest["provider"] == "OpenFreeMap / OpenMapTiles"
    assert manifest["tilejson_endpoint"] == "https://tiles.openfreemap.org/planet"
    assert "OpenStreetMap" in manifest["attribution"]
    assert "transportation" in manifest["vector_layers"]
    assert "landuse" in manifest["vector_layers"]
    assert "style URL" in manifest["style"]
    assert manifest["credential_values_included"] is False
    assert "Hybrid" in manifest["fallback_workflow"]
    assert "access_token" not in serialized
    assert manifest["data_mode"] == "EXTERNAL_GEOPATIAL_VECTOR_TILE_SERVICE"


def test_authenticated_vector_basemap_routes_record_unavailable_safely(monkeypatch, tmp_path):
    old_registry = main.source_registry_service
    old_verification = main.vector_basemap_last_verification
    main.source_registry_service = SourceRegistryService(store_dir=str(tmp_path / "registry"))
    main.vector_basemap_last_verification = {}
    monkeypatch.setattr(main, "verify_vector_basemap", lambda: {
        "status": "UNAVAILABLE", "provider": "openfreemap_openmaptiles",
        "reason": "provider_unreachable", "tiles_loaded": False,
        "credential_configured": False, "credential_values_included": False,
    })
    try:
        client = TestClient(main.app)
        assert client.get("/geospatial/vector-basemap/manifest").status_code == 401
        assert client.post("/geospatial/vector-basemap/verify").status_code == 401
        main.app.dependency_overrides[main.get_identity] = lambda: AuthIdentity(actor="test", roles=["viewer"])
        manifest = client.get("/geospatial/vector-basemap/manifest")
        assert manifest.status_code == 200
        assert manifest.json()["status"] == "CONFIGURED"
        assert client.post("/geospatial/vector-basemap/verify").status_code == 503
        source = main.source_registry_service.get_source("src-gev-openfreemap-vector-basemap")
        assert source.provenance_reference["last_fetch_status"] == "UNAVAILABLE"
        assert source.provenance_reference["credential_values_stored"] is False
    finally:
        main.app.dependency_overrides.pop(main.get_identity, None)
        main.source_registry_service = old_registry
        main.vector_basemap_last_verification = old_verification
