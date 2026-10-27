from copy import deepcopy
import json
from pathlib import Path

from fastapi.testclient import TestClient

import main
from auth.models import AuthIdentity
import integrations.gods_eye_view_dams_connector as dams_connector
from integrations.gods_eye_view_dams_connector import dams_source_path, fetch_dams
from services.artifact_store import ArtifactStore
from services.dam_feature_service import DamFeatureService
from services.source_registry_service import SourceRegistryService


def test_real_dams_snapshot_validates_and_ingests_all_features(tmp_path):
    feed = fetch_dams()
    assert feed["data_mode"] == "STATIC_SNAPSHOT"
    assert feed["source_feature_count"] == 704
    companion = json.loads(dams_source_path().with_suffix(".geojson").read_text(encoding="utf-8-sig"))
    assert companion["type"] == "FeatureCollection"
    assert len(companion["features"]) == feed["source_feature_count"]
    assert companion["features"] == feed["features"]

    service = DamFeatureService(
        ArtifactStore(str(tmp_path / "attributes")),
        ArtifactStore(str(tmp_path / "geometries")),
    )
    result = service.ingest(feed)
    assert result["valid"] == 704
    assert result["rejected"] == 0
    assert result["inserted"] == 704
    assert result["attribute_records"] == result["geometry_records"] == 704
    assert service.list_features(limit=1000)["type"] == "FeatureCollection"
    # The source has one repeated OSM identifier represented by distinct layers.
    duplicated = [r for r in service.list_attributes(limit=1000) if r["osm_id"] == -19953989]
    assert len(duplicated) == 2
    assert {r["source_layer"] for r in duplicated} == {"power_plant", "power_plant_relation_by_geom_type"}


def test_invalid_coordinates_are_rejected_without_losing_valid_features(tmp_path):
    feed = fetch_dams()
    good = deepcopy(feed["features"][0])
    bad = deepcopy(feed["features"][1])
    bad["id"] = "invalid-coordinate-test"
    bad["properties"]["osm_id"] = "invalid-coordinate-test"
    bad["geometry"] = {"type": "Point", "coordinates": [10, 91]}
    feed.update(features=[good, bad], source_feature_count=2, parse_errors=0)
    service = DamFeatureService(
        ArtifactStore(str(tmp_path / "attributes")),
        ArtifactStore(str(tmp_path / "geometries")),
    )
    result = service.ingest(feed)
    assert result["valid"] == 1
    assert result["rejected"] == 1
    assert result["rejection_reasons"] == {"coordinates must be within WGS84 bounds": 1}


def test_bundled_snapshot_is_used_when_sibling_checkout_is_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(dams_connector, "sibling_dams_source_path", lambda: tmp_path / "missing.geojsonl")
    assert dams_connector.dams_source_path() == dams_connector.bundled_dams_source_path()
    assert dams_connector.fetch_dams()["source_feature_count"] == 704


def test_authenticated_api_ingests_reads_back_and_registers_static_snapshot(monkeypatch, tmp_path):
    old_service = main.dam_feature_service
    old_registry = main.source_registry_service
    old_status = main.dam_snapshot_last_verified_at
    main.dam_feature_service = DamFeatureService(
        ArtifactStore(str(tmp_path / "attributes")),
        ArtifactStore(str(tmp_path / "geometries")),
    )
    main.source_registry_service = SourceRegistryService(store_dir=str(tmp_path / "source_registry"))
    main.dam_snapshot_last_verified_at = None
    main.app.dependency_overrides[main.get_identity] = lambda: AuthIdentity(actor="test", roles=["operator"])
    try:
        client = TestClient(main.app)
        ingested = client.post("/dams/ingest")
        assert ingested.status_code == 200, ingested.text
        result = ingested.json()
        assert result["status"] == "STATIC_VERIFIED"
        assert result["source_feature_count"] == 704
        assert result["valid"] == 704 and result["rejected"] == 0
        assert result["readback_counts"] == {"attributes": 704, "geometries": 704}

        attrs = client.get("/dams/attributes?limit=1000")
        geometries = client.get("/dams/features?limit=1000")
        assert attrs.status_code == geometries.status_code == 200
        assert attrs.json()["count"] == 704
        assert geometries.json()["count"] == 704
        assert geometries.json()["features"][0]["geometry"]["type"] in DamFeatureService.GEOMETRY_TYPES

        registry = client.get("/live-datasets").json()
        dataset = next(row for row in registry["datasets"] if row["dataset_id"] == "gods_eye_view_dams")
        assert dataset["status"] == "STATIC_VERIFIED"
        assert dataset["record_count"] == 704
        assert dataset["data_mode"] == "STATIC_SNAPSHOT"
        assert "Dataset Registry" in client.get("/live-datasets/registry").text
    finally:
        main.app.dependency_overrides.pop(main.get_identity, None)
        main.dam_feature_service = old_service
        main.source_registry_service = old_registry
        main.dam_snapshot_last_verified_at = old_status
