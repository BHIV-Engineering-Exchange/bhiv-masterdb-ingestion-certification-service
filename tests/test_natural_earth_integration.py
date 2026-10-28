from fastapi.testclient import TestClient

import main
from auth.models import AuthIdentity
from integrations.natural_earth_connector import load_natural_earth_source
from services.natural_earth_feature_service import NaturalEarthFeatureService
from services.source_registry_service import SourceRegistryService


def test_source_snapshots_have_expected_structures_and_valid_geometries():
    expected = {"regions": (1046, {"Polygon": 934, "MultiPolygon": 112}),
                "marine": (292, {"Polygon": 284, "MultiPolygon": 8})}
    for key, (count, geometry_types) in expected.items():
        source = load_natural_earth_source(key)
        feed = source["feed"]
        assert feed["meta"]["featureCount"] == len(feed["features"]) == count
        assert feed["meta"]["license"] == NaturalEarthFeatureService.LICENSE
        actual_types = {}
        positions = 0
        for feature in feed["features"]:
            validated = NaturalEarthFeatureService.validate_feature(feature)
            kind = validated["geometry"]["type"]
            actual_types[kind] = actual_types.get(kind, 0) + 1
            positions += sum(len(ring) for ring in feature["polygons"])
        assert actual_types == geometry_types
        assert positions == (114297 if key == "regions" else 36754)


def test_authenticated_ingest_api_readback_and_registry_visibility(tmp_path):
    previous = (main.natural_earth_feature_service, main.source_registry_service,
                dict(main.natural_earth_dataset_status), dict(main.natural_earth_last_verified_at))
    main.natural_earth_feature_service = NaturalEarthFeatureService(str(tmp_path / "natural-earth"))
    main.source_registry_service = SourceRegistryService(store_dir=str(tmp_path / "registry"))
    main.natural_earth_dataset_status = {"regions": "UNVERIFIED", "marine": "UNVERIFIED"}
    main.natural_earth_last_verified_at = {"regions": None, "marine": None}
    main.app.dependency_overrides[main.get_identity] = lambda: AuthIdentity(actor="test", roles=["operator"])
    try:
        client = TestClient(main.app)
        for key, count in (("regions", 1046), ("marine", 292)):
            response = client.post(f"/natural-earth/{key}/ingest")
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["status"] == "STATIC_VERIFIED"
            assert result["valid"] == count and result["rejected"] == 0
            assert result["attribute_records"] == result["geometry_records"] == count
            assert result["api_attribute_readback"] == result["api_feature_readback"] == count
            assert result["registry_readback"] is True

            attrs = client.get(f"/natural-earth/{key}/attributes?limit=1").json()
            features = client.get(f"/natural-earth/{key}/features?limit=1").json()
            assert attrs["total"] == features["total"] == count
            assert attrs["features"][0]["attributes"]["name"]
            assert features["features"][0]["geometry"]["type"] in {"Polygon", "MultiPolygon"}
            geometry = features["features"][0]["geometry"]
            first_ring = geometry["coordinates"][0] if geometry["type"] == "Polygon" else geometry["coordinates"][0][0]
            assert first_ring[0] == first_ring[-1]

        listing = client.get("/live-datasets").json()["datasets"]
        for key, count in (("regions", 1046), ("marine", 292)):
            item = next(row for row in listing if row["dataset_id"] == f"gods_eye_view_natural_earth_{key}")
            assert item["status"] == "STATIC_VERIFIED"
            assert item["data_mode"] == "STATIC_SNAPSHOT"
            assert item["record_count"] == count and item["geometry_record_count"] == count
            assert "Natural Earth" in item["attribution"]
        assert "Verify service" in client.get("/live-datasets/registry").text
    finally:
        main.app.dependency_overrides.pop(main.get_identity, None)
        (main.natural_earth_feature_service, main.source_registry_service,
         main.natural_earth_dataset_status, main.natural_earth_last_verified_at) = previous


def test_read_endpoints_require_authentication():
    client = TestClient(main.app)
    assert client.get("/natural-earth/regions/features").status_code in (401, 403)
