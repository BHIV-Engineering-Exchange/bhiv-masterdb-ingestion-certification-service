import json

from fastapi.testclient import TestClient
import pytest

import main
from auth.models import AuthIdentity
from integrations.aisstream_connector import AISStreamConnector, normalize_position
from services.ais_observation_service import AISObservationService, AISObservationValidationError
from services.artifact_store import ArtifactStore
from services.source_registry_service import SourceRegistryService


def raw_position(mmsi=368207620, speed=12.4):
    return {
        "MessageType": "PositionReport",
        "MetaData": {"MMSI": mmsi, "ShipName": "TEST VESSEL", "Latitude": 25.7617, "Longitude": -80.1918},
        "Message": {"PositionReport": {"UserID": mmsi, "Sog": speed, "Cog": 86.7, "Timestamp": 30}},
    }


class FakeConnection:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.subscription = None
        self.closed = False

    def send(self, payload):
        self.subscription = json.loads(payload)

    def recv(self):
        return next(self.messages)

    def close(self):
        self.closed = True


def test_connector_normalizes_binary_position_and_skips_invalid_messages():
    connection = FakeConnection([
        json.dumps({"MessageType": "SubscriptionConfirmation"}).encode(),
        json.dumps({"MessageType": "PositionReport", "MetaData": {"MMSI": 1}}),
        json.dumps(raw_position()).encode(),
    ])
    connector = AISStreamConnector(api_key="test-key", connection_factory=lambda *args, **kwargs: connection)
    feed = connector.fetch_positions([[[25.9, -80.3], [25.6, -79.8]]], max_messages=1)
    assert feed["record_count"] == 1
    assert feed["observations"][0]["vessel_id"] == "368207620"
    assert connection.subscription["APIKey"] == "test-key"
    assert connection.closed


def test_normalization_rejects_missing_coordinates():
    message = raw_position()
    del message["MetaData"]["Latitude"]
    del message["MetaData"]["Longitude"]
    assert normalize_position(message) is None


def test_connector_reconnects_after_a_connection_error():
    connection = FakeConnection([json.dumps(raw_position())])
    calls = []

    def factory(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("temporary network failure")
        return connection

    connector = AISStreamConnector(api_key="test-key", connection_factory=factory)
    feed = connector.fetch_positions([[[25.9, -80.3], [25.6, -79.8]]], max_messages=1)
    assert feed["record_count"] == 1
    assert feed["connection_errors"] == ["OSError"]


def test_service_updates_existing_vessel_and_rejects_invalid_batch(tmp_path):
    service = AISObservationService(ArtifactStore(str(tmp_path)))
    first = normalize_position(raw_position())
    assert first is not None
    assert service.ingest({"source": "AISStream", "observations": [first]})["inserted"] == 1
    second = normalize_position(raw_position(speed=9.1))
    assert second is not None
    assert service.ingest({"source": "AISStream", "observations": [second]})["updated"] == 1
    assert len(service.list()) == 1
    assert service.list()[0]["speed_knots"] == 9.1
    with pytest.raises(AISObservationValidationError):
        service.ingest({"source": "AISStream", "observations": [{"vessel_id": "1"}]})
    assert len(service.list()) == 1


def test_api_ingests_and_reads_normalized_positions(monkeypatch, tmp_path):
    previous = main.ais_observation_service
    previous_registry = main.source_registry_service
    previous_feed_state = main.observation_feed_state["aisstream"]
    main.ais_observation_service = AISObservationService(ArtifactStore(str(tmp_path)))
    main.source_registry_service = SourceRegistryService(store_dir=str(tmp_path / "registry"))
    main.observation_feed_state["aisstream"] = {"status": "PENDING", "last_verified_at_utc": None}
    event = normalize_position(raw_position())
    monkeypatch.setattr(main, "fetch_aisstream_positions", lambda **kwargs: {"source": "AISStream", "observations": [event], "connection_errors": []})
    main.app.dependency_overrides[main.get_identity] = lambda: AuthIdentity(actor="test", roles=["operator"])
    try:
        client = TestClient(main.app)
        response = client.post("/aisstream/ingest", json={"bounding_boxes": [[[25.9, -80.3], [25.6, -79.8]]], "max_messages": 1})
        assert response.status_code == 200
        assert response.json()["inserted"] == 1
        assert response.json()["status"] == "LIVE_VERIFIED"
        assert response.json()["readback_records"] == 1
        assert response.json()["registry_readback"] is True
        listed = client.get("/aisstream/observations")
        assert listed.status_code == 200
        assert listed.json()["observations"][0]["vessel_id"] == "368207620"
        source = main.source_registry_service.get_source("src-gev-aisstream-vessels")
        assert source.provenance_reference["last_fetch_status"] == "LIVE_VERIFIED"
    finally:
        main.app.dependency_overrides.pop(main.get_identity, None)
        main.ais_observation_service = previous
        main.source_registry_service = previous_registry
        main.observation_feed_state["aisstream"] = previous_feed_state


def test_empty_aisstream_batch_stays_pending(monkeypatch, tmp_path):
    previous = (main.ais_observation_service, main.source_registry_service,
                main.observation_feed_state["aisstream"])
    main.ais_observation_service = AISObservationService(ArtifactStore(str(tmp_path / "ais")))
    main.source_registry_service = SourceRegistryService(store_dir=str(tmp_path / "registry"))
    main.observation_feed_state["aisstream"] = {"status": "PENDING", "last_verified_at_utc": None}
    monkeypatch.setattr(main, "fetch_aisstream_positions", lambda **kwargs: {
        "source": "AISStream", "observations": [], "connection_errors": [],
    })
    main.app.dependency_overrides[main.get_identity] = lambda: AuthIdentity(actor="test", roles=["operator"])
    try:
        response = TestClient(main.app).post("/aisstream/ingest", json={
            "bounding_boxes": [[[25.9, -80.3], [25.6, -79.8]]], "max_messages": 1,
        })
        assert response.status_code == 200
        assert response.json()["status"] == "PENDING"
        source = main.source_registry_service.get_source("src-gev-aisstream-vessels")
        assert source.provenance_reference["last_fetch_status"] == "PENDING"
    finally:
        main.app.dependency_overrides.pop(main.get_identity, None)
        (main.ais_observation_service, main.source_registry_service,
         main.observation_feed_state["aisstream"]) = previous
