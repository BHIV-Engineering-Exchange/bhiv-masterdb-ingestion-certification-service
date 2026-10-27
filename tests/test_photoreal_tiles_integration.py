import json

from fastapi.testclient import TestClient

import main
from auth.models import AuthIdentity
from integrations import gods_eye_view_photoreal_tiles_connector as connector
from integrations.gods_eye_view_photoreal_tiles_connector import ProviderCredentials
from services.source_registry_service import SourceRegistryService


def test_safe_manifest_never_returns_provider_credentials(monkeypatch):
    google_secret = "fake-google-secret-do-not-return"
    ion_secret = "fake-ion-secret-do-not-return"
    credentials = ProviderCredentials(google_secret, ion_secret)
    monkeypatch.setattr(connector, "resolve_credentials", lambda: credentials)

    payload = connector.safe_manifest()
    serialized = json.dumps(payload)
    assert payload["preferred_route"] == "google-direct"
    assert payload["fallback_route"] == "google-ion"
    assert payload["credential_configured"] is True
    assert payload["credential_values_included"] is False
    assert google_secret not in serialized
    assert ion_secret not in serialized
    assert google_secret not in repr(credentials)
    assert ion_secret not in repr(credentials)
    assert "?key=" not in serialized
    assert "access_token=" not in serialized


def test_no_credentials_is_unavailable_without_attempting_fake_tiles(monkeypatch):
    monkeypatch.setattr(connector, "resolve_credentials", lambda: ProviderCredentials(None, None))
    result = connector.verify_photoreal_tiles()
    assert result == {
        "status": "UNAVAILABLE",
        "reason": "provider_credentials_not_configured",
        "credential_configured": False,
        "tiles_loaded": False,
    }


def test_authenticated_manifest_registry_and_unavailable_verification(monkeypatch, tmp_path):
    old_registry = main.source_registry_service
    old_verification = main.photoreal_tiles_last_verification
    registry = SourceRegistryService(store_dir=str(tmp_path / "source_registry"))
    main.source_registry_service = registry
    main.photoreal_tiles_last_verification = {}
    monkeypatch.setattr(connector, "resolve_credentials", lambda: ProviderCredentials(None, None))
    assert TestClient(main.app).get("/geospatial/3d-tiles/photorealistic/manifest").status_code == 401
    main.app.dependency_overrides[main.get_identity] = lambda: AuthIdentity(actor="test", roles=["operator"])
    try:
        client = TestClient(main.app)
        manifest = client.get("/geospatial/3d-tiles/photorealistic/manifest")
        assert manifest.status_code == 200
        assert manifest.json()["status"] == "UNAVAILABLE"
        assert manifest.json()["provider"] == "Google Maps Platform Photorealistic 3D Tiles via CesiumJS"
        assert manifest.json()["credential_values_included"] is False

        verification = client.post("/geospatial/3d-tiles/photorealistic/verify")
        assert verification.status_code == 503
        assert "Photorealistic tiles unavailable" in verification.json()["error"]["message"]
        source_record = registry.get_source("src-gev-google-photoreal-tiles")
        assert source_record.provenance_reference["last_fetch_status"] == "UNAVAILABLE"
        assert source_record.provenance_reference["credential_values_stored"] is False
        assert source_record.provenance_reference["last_verification"]["tiles_loaded"] is False

        registry_response = client.get("/live-datasets")
        assert registry_response.status_code == 200
        item = next(row for row in registry_response.json()["datasets"] if row["dataset_id"] == "google_cesium_photorealistic_3d_tiles")
        assert item["status"] == "UNAVAILABLE"
        assert item["credential_values_included"] is False
        assert "manifest_endpoint" in item and "verification_endpoint" in item
        assert client.get("/live-datasets/registry").status_code == 200
    finally:
        main.app.dependency_overrides.pop(main.get_identity, None)
        main.source_registry_service = old_registry
        main.photoreal_tiles_last_verification = old_verification
