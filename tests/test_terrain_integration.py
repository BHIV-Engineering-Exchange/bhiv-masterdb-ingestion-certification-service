import json

from fastapi.testclient import TestClient

import main
from auth.models import AuthIdentity
from integrations import gods_eye_view_terrain_connector as connector
from services.source_registry_service import SourceRegistryService


def test_terrain_manifest_is_safe_and_identifies_real_providers(monkeypatch):
    token = "never-serialize-this-ion-token"
    monkeypatch.setenv("CESIUM_ION_TOKEN", token)
    manifest = connector.safe_manifest()
    serialized = json.dumps(manifest)
    assert manifest["provider"] == "Cesium World Terrain via Cesium ion"
    assert manifest["endpoints"]["cesium_ion_asset_id"] == 1
    assert token not in serialized
    assert "access_token=" not in serialized
    monkeypatch.delenv("CESIUM_ION_TOKEN")
    keyless = connector.safe_manifest()
    assert keyless["provider"] == "Re:Earth Terrain / Mapterhorn"
    assert "CC BY 4.0" in keyless["attribution"]
    assert keyless["endpoints"]["reearth_layer"].endswith("/layer.json")


def test_authenticated_terrain_routes_and_unavailable_registry_status(monkeypatch, tmp_path):
    monkeypatch.delenv("CESIUM_ION_TOKEN", raising=False)
    old_registry = main.source_registry_service
    old_verification = main.world_terrain_last_verification
    main.source_registry_service = SourceRegistryService(store_dir=str(tmp_path / "registry"))
    main.world_terrain_last_verification = {}
    monkeypatch.setattr(main, "verify_world_terrain", lambda: {
        "status": "UNAVAILABLE", "reason": "provider_unreachable", "tiles_loaded": False,
        "credential_configured": False, "credential_values_included": False,
    })
    try:
        client = TestClient(main.app)
        assert client.get("/geospatial/terrain/manifest").status_code == 401
        assert client.post("/geospatial/terrain/verify").status_code == 401
        main.app.dependency_overrides[main.get_identity] = lambda: AuthIdentity(actor="test", roles=["viewer"])
        manifest = client.get("/geospatial/terrain/manifest")
        assert manifest.status_code == 200
        assert manifest.json()["provider"] == "Re:Earth Terrain / Mapterhorn"
        assert client.post("/geospatial/terrain/verify").status_code == 503
        source = main.source_registry_service.get_source("src-gev-world-3d-terrain")
        assert source.provenance_reference["last_fetch_status"] == "UNAVAILABLE"
        assert source.provenance_reference["credential_values_stored"] is False
    finally:
        main.app.dependency_overrides.pop(main.get_identity, None)
        main.source_registry_service = old_registry
        main.world_terrain_last_verification = old_verification
