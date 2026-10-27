from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

import main
from auth.models import AuthIdentity
import integrations.gods_eye_view_bhote_koshi_connector as bhote_connector
from integrations.gods_eye_view_bhote_koshi_connector import fetch_bhote_koshi_event
from services.artifact_store import ArtifactStore
from services.bhote_koshi_event_service import BhoteKoshiEventService, BhoteKoshiValidationError
from services.source_registry_service import SourceRegistryService


def service_at(root):
    return BhoteKoshiEventService(
        ArtifactStore(str(root / "events")),
        ArtifactStore(str(root / "geometries")),
        ArtifactStore(str(root / "media")),
    )


def test_real_source_shape_validation_and_separate_storage(tmp_path):
    feed = fetch_bhote_koshi_event()
    assert feed["data_mode"] == "STATIC_HISTORICAL_RECONSTRUCTION"
    assert feed["event"]["id"] == "bhote-koshi-2026"
    assert feed["event"]["observedDate"] == "2026-08-26"
    assert len(feed["flood_path_coordinates"]) == 489
    assert len(feed["event"]["evidenceSpine"]) == 16
    assert len(feed["event"]["witnessAnchors"]) == 1
    assert feed["presentation_metadata"]["playback_seconds"] == 90

    service = service_at(tmp_path)
    result = service.ingest(feed)
    assert result["valid_counts"] == {"events": 1, "geometries": 19, "media": 16}
    assert result["rejected_counts"] == {"event": 0, "geometry": 0, "media": 0}
    assert result["inserted"] == {"events": 1, "geometries": 19, "media": 16}
    repeated = service.ingest(feed)
    assert repeated["updated"] == {"events": 1, "geometries": 19, "media": 16}
    assert repeated["inserted"] == {"events": 0, "geometries": 0, "media": 0}
    assert len(service.get_event()["event"]["evidenceSpine"]) == 16
    assert service.list_features(limit=1000)["total"] == 19
    assert len(service.list_media(limit=1000)) == 16
    # Original capture times are null/unverified and remain so in storage.
    assert all(row["timing"]["capturedAt"] is None for row in service.get_event()["event"]["evidenceSpine"])
    assert all(row["media"]["rightsStatus"].endswith("not redistributed.") for row in service.list_media(limit=1000))
    assert all(row["source_provenance"]["files"] == feed["source_files"] for row in service.list_media(limit=1000))


def test_source_validation_rejects_invalid_flood_path(tmp_path):
    feed = deepcopy(fetch_bhote_koshi_event())
    feed["flood_path_coordinates"][0][1] = 95
    with pytest.raises(BhoteKoshiValidationError, match="WGS84"):
        service_at(tmp_path).ingest(feed)


def test_bundled_source_is_used_when_sibling_checkout_is_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(bhote_connector, "source_root", lambda: tmp_path / "missing-gods-eye-view")
    feed = fetch_bhote_koshi_event()
    assert feed["event"]["id"] == "bhote-koshi-2026"
    assert len(feed["flood_path_coordinates"]) == 489


def test_authenticated_api_ingests_reads_back_and_registers_static_event(tmp_path):
    old_service = main.bhote_koshi_event_service
    old_registry = main.source_registry_service
    old_verified_at = main.bhote_koshi_last_verified_at
    main.bhote_koshi_event_service = service_at(tmp_path / "api")
    main.source_registry_service = SourceRegistryService(store_dir=str(tmp_path / "registry"))
    main.bhote_koshi_last_verified_at = None
    assert TestClient(main.app).get("/events/bhote-koshi").status_code == 401
    main.app.dependency_overrides[main.get_identity] = lambda: AuthIdentity(actor="test", roles=["operator"])
    try:
        client = TestClient(main.app)
        ingest = client.post("/events/bhote-koshi/ingest")
        assert ingest.status_code == 200, ingest.text
        result = ingest.json()
        assert result["status"] == "STATIC_VERIFIED"
        assert result["readback_counts"] == {"events": 1, "geometries": 19, "media_references": 16}

        event = client.get("/events/bhote-koshi")
        features = client.get("/events/bhote-koshi/features?limit=1000")
        media = client.get("/events/bhote-koshi/media?limit=1000")
        assert event.status_code == features.status_code == media.status_code == 200
        assert event.json()["event"]["id"] == "bhote-koshi-2026"
        assert features.json()["total"] == 19
        assert len(media.json()["media_references"]) == 16

        registry = client.get("/live-datasets").json()
        row = next(item for item in registry["datasets"] if item["dataset_id"] == "gods_eye_view_bhote_koshi_flood")
        assert row["status"] == "STATIC_VERIFIED"
        assert row["data_mode"] == "STATIC_HISTORICAL_RECONSTRUCTION"
        assert row["event_record_count"] == 1
        assert row["geometry_record_count"] == 19
        assert row["media_reference_count"] == 16
        assert client.get("/live-datasets/registry").status_code == 200
    finally:
        main.app.dependency_overrides.pop(main.get_identity, None)
        main.bhote_koshi_event_service = old_service
        main.source_registry_service = old_registry
        main.bhote_koshi_last_verified_at = old_verified_at
