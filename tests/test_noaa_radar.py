import struct
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main
from auth.models import AuthIdentity
from integrations import noaa_radar_connector as radar


def manifest():
    return {
        "schemaVersion": 1, "product": "radar", "title": "CONUS radar reflectivity",
        "coverage": "Contiguous United States", "description": "Observed MRMS radar base reflectivity.",
        "source": "NOAA nowCOAST", "attribution": "NOAA/NWS nowCOAST",
        "bounds": {"west": -127.0, "south": 24.0, "east": -65.0, "north": 50.0},
        "times": ["2026-10-24T09:00:00Z"], "latest": "2026-10-24T09:00:00Z",
        "fetchedAt": 1792832400000, "stale": False, "unavailable": False,
    }


def satellite_manifest(product):
    payload = manifest()
    payload["product"] = product
    payload["title"] = {"clouds": "Global satellite infrared", "clouds-regional": "GOES regional satellite infrared", "lightning": "Lightning density"}[product]
    payload["times"] = ["2026-10-24T09:00:00.000Z"]
    payload["latest"] = payload["times"][0]
    payload["bounds"] = {"west": -130.0, "south": -60.0, "east": 180.0, "north": 60.0} if product == "clouds" else ({"west": -160.0, "south": -60.0, "east": -20.0, "north": 60.0} if product == "clouds-regional" else {"west": -180.0, "south": -25.0, "east": 180.0, "north": 80.0})
    payload["imageSize"] = {"width": 2048, "height": 1024} if product == "clouds" else {"width": 4096, "height": 2048}
    return payload


def test_radar_manifest_and_png_validation():
    payload = manifest()
    assert radar._validate_manifest(payload)["latest"] == "2026-10-24T09:00:00Z"
    payload["stale"] = True
    with pytest.raises(radar.RadarUpstreamError):
        radar._validate_manifest(payload)
    png = bytearray(33)
    png[:8] = b"\x89PNG\r\n\x1a\n"
    struct.pack_into(">I", png, 8, 13)
    png[12:16] = b"IHDR"
    struct.pack_into(">II", png, 16, 256, 256)
    assert radar._validate_png(bytes(png), 256, 256) == (256, 256)
    with pytest.raises(radar.RadarUpstreamError):
        radar._validate_png(bytes(png), 512, 512)


@pytest.mark.parametrize("product,layer", [("clouds", "global_longwave_imagery_mosaic"), ("clouds-regional", "goes_longwave_imagery")])
def test_satellite_manifest_product_layers_and_limits(product, layer):
    assert radar._validate_manifest(satellite_manifest(product), product)["product"] == product
    assert radar.PRODUCT_LAYERS[product] == layer
    assert ("2048x1024" in radar.PRODUCT_IMAGE_SIZES[product])
    if product == "clouds":
        assert "4096x2048" not in radar.PRODUCT_IMAGE_SIZES[product]


def test_lightning_manifest_layer_and_product_size():
    assert radar._validate_manifest(satellite_manifest("lightning"), "lightning")["product"] == "lightning"
    assert radar.PRODUCT_LAYERS["lightning"] == "ldn_lightning_strike_density"
    assert radar.PRODUCT_IMAGE_SIZES["lightning"] == {"1024x512", "2048x1024", "4096x2048"}


def test_satellite_manifest_image_routes_and_error_handling(monkeypatch):
    old_state, old_registry = main.satellite_cloud_state, main.source_registry_service
    main.satellite_cloud_state = {
        product: {"last_verified_at_utc": None, "last_fetch_status": "CONFIGURED", "metadata": None, "last_image_retrieval": None}
        for product in ("clouds", "clouds-regional", "lightning")
    }

    class Registry:
        def __init__(self): self.records = {}
        def mark_fetch_status(self, source_id, status, metadata):
            record = self.records.setdefault(source_id, {"last_validation": "NOT VERIFIED", "provenance_reference": {}})
            record["provenance_reference"].update(metadata)
            record["provenance_reference"]["last_fetch_status"] = status
        def mark_validated(self, source_id, at, metadata):
            record = self.records.setdefault(source_id, {"last_validation": "NOT VERIFIED", "provenance_reference": {}})
            record["last_validation"] = at
            record["provenance_reference"].update(metadata)
        def get_source(self, source_id):
            record = self.records[source_id]
            return SimpleNamespace(last_validation=record["last_validation"], provenance_reference=record["provenance_reference"])

    registry = Registry()
    main.source_registry_service = registry
    monkeypatch.setattr(main, "fetch_weather_manifest", lambda product: satellite_manifest(product))
    monkeypatch.setattr(main, "fetch_weather_tile", lambda product, time, z, x, y, size="256": (b"png", {"width": 256, "height": 256, "bytes": 3, "content_type": "image/png"}))
    monkeypatch.setattr(main, "fetch_weather_image", lambda product, time, size=None, bbox=None: (b"png", {"width": 2048, "height": 1024, "bytes": 3, "content_type": "image/png"}))
    main.app.dependency_overrides[main.get_identity] = lambda: AuthIdentity(actor="satellite-test", roles=["viewer"])
    try:
        client = TestClient(main.app)
        global_manifest = client.get("/weather/satellite/manifest?product=clouds")
        assert global_manifest.status_code == 200
        assert global_manifest.json()["layer"] == "global_longwave_imagery_mosaic"
        timestamp = global_manifest.json()["latest"]
        image = client.get("/weather/satellite/image", params={"product": "clouds", "time": timestamp})
        assert image.status_code == 200 and image.headers["content-type"] == "image/png"
        regional = client.post("/weather/satellite/verify?product=clouds-regional")
        assert regional.status_code == 200
        assert regional.json()["layer"] == "goes_longwave_imagery"
        assert regional.json()["metadata_readback"] is True
        lightning_manifest = client.get("/weather/lightning/manifest")
        assert lightning_manifest.status_code == 200
        assert lightning_manifest.json()["layer"] == "ldn_lightning_strike_density"
        lightning_time = lightning_manifest.json()["latest"]
        lightning_image = client.get("/weather/lightning/image", params={"time": lightning_time})
        lightning_tile = client.get("/weather/lightning/tile", params={"time": lightning_time, "z": 2, "x": 2, "y": 1})
        assert lightning_image.status_code == lightning_tile.status_code == 200
        assert lightning_image.headers["content-type"] == lightning_tile.headers["content-type"] == "image/png"
        lightning_verified = client.post("/weather/lightning/verify")
        assert lightning_verified.status_code == 200 and lightning_verified.json()["metadata_readback"] is True
        invalid_time = client.get("/weather/satellite/tile", params={"product": "clouds", "time": "2000-01-01T00:00:00Z", "z": 2, "x": 2, "y": 1})
        unsupported = client.get("/weather/satellite/manifest?product=moon")
        assert invalid_time.status_code == unsupported.status_code == 422
        assert main.satellite_cloud_state["clouds"]["last_fetch_status"] == "LIVE_VERIFIED"
        assert main.satellite_cloud_state["clouds-regional"]["last_fetch_status"] == "LIVE_VERIFIED"
        assert main.satellite_cloud_state["lightning"]["last_fetch_status"] == "LIVE_VERIFIED"
    finally:
        main.app.dependency_overrides.pop(main.get_identity, None)
        main.satellite_cloud_state, main.source_registry_service = old_state, old_registry


@pytest.mark.parametrize("product", ["clouds", "lightning"])
def test_satellite_manifest_upstream_failure_sets_unavailable(monkeypatch, product):
    old_state, old_registry = main.satellite_cloud_state, main.source_registry_service
    main.satellite_cloud_state = {p: {"last_verified_at_utc": None, "last_fetch_status": "CONFIGURED", "metadata": None, "last_image_retrieval": None} for p in ("clouds", "clouds-regional", "lightning")}

    class Registry:
        last_status = None
        def mark_fetch_status(self, source_id, status, metadata): self.last_status = status

    registry = Registry()
    main.source_registry_service = registry
    def fail(product):
        raise radar.RadarUpstreamError("upstream unavailable")
    monkeypatch.setattr(main, "fetch_weather_manifest", fail)
    main.app.dependency_overrides[main.get_identity] = lambda: AuthIdentity(actor="satellite-error-test", roles=["viewer"])
    try:
        path = "/weather/lightning/manifest" if product == "lightning" else "/weather/satellite/manifest?product=clouds"
        response = TestClient(main.app).get(path)
        assert response.status_code == 502
        assert registry.last_status == "UNAVAILABLE"
        assert main.satellite_cloud_state[product]["last_fetch_status"] == "UNAVAILABLE"
    finally:
        main.app.dependency_overrides.pop(main.get_identity, None)
        main.satellite_cloud_state, main.source_registry_service = old_state, old_registry


def test_radar_verify_registers_metadata_only_after_tile_readback(monkeypatch):
    old_state, old_registry = main.radar_source_state, main.source_registry_service
    main.radar_source_state = {"last_verified_at_utc": None, "last_fetch_status": "CONFIGURED", "metadata": None, "last_image_retrieval": None}

    class Registry:
        def __init__(self):
            self.provenance = {}
            self.last_validation = "NOT VERIFIED"
        def mark_fetch_status(self, source_id, status, metadata):
            self.provenance.update(metadata)
            self.provenance["last_fetch_status"] = status
        def mark_validated(self, source_id, validated_at, metadata):
            self.last_validation = validated_at
            self.provenance.update(metadata)
        def get_source(self, source_id):
            return SimpleNamespace(last_validation=self.last_validation, provenance_reference=self.provenance)

    registry = Registry()
    main.source_registry_service = registry
    monkeypatch.setattr(main, "fetch_radar_manifest", manifest)
    monkeypatch.setattr(main, "fetch_radar_tile", lambda *args, **kwargs: (b"png", {"width": 256, "height": 256, "bytes": 3, "content_type": "image/png"}))
    main.app.dependency_overrides[main.get_identity] = lambda: AuthIdentity(actor="radar-test", roles=["viewer"])
    try:
        client = TestClient(main.app)
        response = client.post("/weather/radar/verify")
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "LIVE_VERIFIED" and result["metadata_readback"] is True
        assert result["available_radar_timestamps"] == ["2026-10-24T09:00:00Z"]
        assert registry.provenance["radar_metadata"]["layer"] == "conus_base_reflectivity_mosaic"
        row = next(d for d in client.get("/live-datasets").json()["datasets"] if d["dataset_id"] == "noaa_nowcoast_conus_base_reflectivity_radar")
        assert row["status"] == "LIVE_VERIFIED" and row["record_count"] == 0
    finally:
        main.app.dependency_overrides.pop(main.get_identity, None)
        main.radar_source_state, main.source_registry_service = old_state, old_registry
