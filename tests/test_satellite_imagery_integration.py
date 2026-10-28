import json

from fastapi.testclient import TestClient

import main
from auth.models import AuthIdentity
from integrations import gods_eye_view_satellite_imagery_connector as connector
from services.source_registry_service import SourceRegistryService


def test_manifest_is_safe_and_contains_provider_credits(monkeypatch):
    monkeypatch.setenv("CESIUM_ION_TOKEN", "do-not-return-this-ion-token")
    manifest = connector.safe_manifest()
    serialized = json.dumps(manifest)
    assert manifest["preferred_provider"] == "Esri World Imagery"
    assert "OpenStreetMap" in manifest["fallback_providers"][-1]
    assert "© OpenStreetMap contributors" in manifest["attribution"]
    assert "Maxar" in manifest["attribution"]
    assert "do-not-return-this-ion-token" not in serialized
    assert "access_token=" not in serialized
    assert manifest["data_mode"] == "EXTERNAL_GEOPATIAL_TILE_SERVICE"


def test_authenticated_satellite_imagery_routes_and_registry(monkeypatch, tmp_path):
    old_registry = main.source_registry_service
    old_verification = main.satellite_imagery_last_verification
    main.source_registry_service = SourceRegistryService(store_dir=str(tmp_path / "registry"))
    main.satellite_imagery_last_verification = {}
    monkeypatch.setattr(main, "verify_satellite_imagery", lambda: {
        "status": "UNAVAILABLE", "reason": "all_provider_tiles_unavailable", "tiles_loaded": False,
    })
    try:
        client = TestClient(main.app)
        assert client.get("/geospatial/satellite-imagery/manifest").status_code == 401
        assert client.post("/geospatial/satellite-imagery/verify").status_code == 401
        main.app.dependency_overrides[main.get_identity] = lambda: AuthIdentity(actor="test", roles=["viewer"])
        manifest = client.get("/geospatial/satellite-imagery/manifest")
        assert manifest.status_code == 200
        assert manifest.json()["status"] == "CONFIGURED"
        assert client.post("/geospatial/satellite-imagery/verify").status_code == 503
        source = main.source_registry_service.get_source("src-gev-world-satellite-imagery")
        assert source.provenance_reference["last_fetch_status"] == "UNAVAILABLE"
    finally:
        main.app.dependency_overrides.pop(main.get_identity, None)
        main.source_registry_service = old_registry
        main.satellite_imagery_last_verification = old_verification
