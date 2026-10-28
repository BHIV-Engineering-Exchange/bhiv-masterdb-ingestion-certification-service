import struct

from fastapi.testclient import TestClient

import main
from auth.models import AuthIdentity
from integrations.tomtom_traffic_connector import decode_flow_tile, fetch_flow_tiles, validate_tile_coord
from services.artifact_store import ArtifactStore
from services.traffic_observation_service import TrafficObservationService


def _varint(value):
    out = bytearray()
    while value > 0x7f:
        out.append((value & 0x7f) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def _field(number, wire, value):
    tag = _varint((number << 3) | wire)
    if wire == 2:
        return tag + _varint(len(value)) + value
    if wire in (1, 5):
        return tag + value
    return tag + _varint(value)


def _string(value):
    return value.encode("utf-8")


def _sample_tile():
    tags = bytes([0, 0, 1, 1, 2, 2])
    geom = b"".join(_varint(v) for v in (9, 2000, 2000, 10, 200, 200))
    feature = _field(2, 2, tags) + _field(3, 0, _varint(2)[0]) + _field(4, 2, geom)
    vals = [
        _field(3, 1, struct.pack("<d", 0.4)),
        _field(1, 2, _string("Major road")),
        _field(1, 2, _string("one_side")),
    ]
    layer = _field(1, 2, _string("Traffic flow")) + _field(2, 2, feature)
    for key in ("traffic_level", "road_type", "traffic_road_coverage"):
        layer += _field(3, 2, _string(key))
    for value in vals:
        layer += _field(4, 2, value)
    layer += _field(5, 0, 4096)
    return _field(3, 2, layer)


def _record():
    return decode_flow_tile(_sample_tile(), 12, 1204, 1540, "2026-10-24T08:30:00+00:00")[0]


def test_decode_mvt_preserves_tile_geometry_and_relative_flow():
    segment = _record()
    assert segment["traffic_level"] == 0.4
    assert segment["speed_ratio"] == 0.4
    assert segment["congestion_ratio"] == 0.6
    assert segment["road_type"] == "Major road"
    assert segment["tile"] == {"z": 12, "x": 1204, "y": 1540}
    assert len(segment["coordinates"]) == 2
    assert segment["current_speed_kph"] is None
    assert segment["free_flow_speed_kph"] is None


def test_tile_validation_and_traffic_store_idempotency(tmp_path):
    assert validate_tile_coord({"z": 12, "x": 1204, "y": 1540})["z"] == 12
    try:
        validate_tile_coord({"z": 12, "x": 4096, "y": 0})
    except ValueError:
        pass
    else:
        raise AssertionError("invalid tile coordinates must be rejected")
    service = TrafficObservationService(ArtifactStore(str(tmp_path)))
    segment = _record()
    first = service.ingest({"source": "TomTom Traffic API", "observations": [segment, {**segment, "congestion_ratio": 2}]})
    second = service.ingest({"source": "TomTom Traffic API", "observations": [segment]})
    assert first["inserted"] == 1 and first["skipped"] == 1
    assert second["updated"] == 1
    assert len(service.list()) == 1


def test_upstream_fetch_uses_server_key_and_decodes_binary_tile(monkeypatch):
    monkeypatch.setenv("TOMTOM_API_KEY", "test-server-key")

    class Response:
        content = _sample_tile()
        headers = {"Date": "Sat, 24 Oct 2026 08:30:00 GMT"}

        def raise_for_status(self):
            return None

    def fake_get(url, *, params, timeout):
        assert "/relative/12/1204/1540.pbf" in url
        assert "test-server-key" not in url
        assert params == {"key": "test-server-key"}
        return Response()

    monkeypatch.setattr("integrations.tomtom_traffic_connector.requests.get", fake_get)
    feed = fetch_flow_tiles([{"z": 12, "x": 1204, "y": 1540}])
    assert feed["tile_count"] == 1
    assert feed["record_count"] == 1
    assert feed["observations"][0]["observation_time_utc"] == "2026-10-24T08:30:00+00:00"


def test_traffic_api_readback_and_registry_visibility(tmp_path, monkeypatch):
    old = (main.traffic_observation_service, main.traffic_last_verified_at, main.traffic_verified_tiles, main.traffic_last_fetch_error)
    main.traffic_observation_service = TrafficObservationService(ArtifactStore(str(tmp_path)))
    main.traffic_last_verified_at = None
    main.traffic_verified_tiles = []
    main.traffic_last_fetch_error = False
    monkeypatch.setenv("TOMTOM_API_KEY", "configured")
    tile = {"z": 12, "x": 1204, "y": 1540}
    monkeypatch.setattr(main, "fetch_flow_tiles", lambda tiles: {"source": "TomTom Traffic API", "tile_count": 1,
        "tiles": [{**tile, "segment_count": 1, "observation_time_utc": "2026-10-24T08:30:00+00:00"}], "record_count": 1,
        "observations": [_record()]})
    main.app.dependency_overrides[main.get_identity] = lambda: AuthIdentity(actor="test", roles=["viewer"])
    try:
        client = TestClient(main.app)
        ingested = client.post("/traffic/tomtom/ingest", json={"tiles": [tile]})
        assert ingested.status_code == 200
        assert ingested.json()["inserted"] == 1
        readback = client.get("/traffic/tomtom/observations?z=12&x=1204&y=1540").json()
        assert readback["count"] == 1
        assert readback["observations"][0]["tile"] == tile
        registry = client.get("/live-datasets").json()
        entry = next(item for item in registry["datasets"] if item["dataset_id"] == "tomtom_traffic_flow_segments")
        assert entry["status"] == "LIVE_VERIFIED"
        assert entry["data_mode"] == "LIVE_ONLY"
        assert entry["verified_tiles"] == [tile]
        monkeypatch.setattr(main, "fetch_flow_tiles", lambda _: (_ for _ in ()).throw(main.TomTomUpstreamError("HTTP 401")))
        failed = client.post("/traffic/tomtom/ingest", json={"tiles": [tile]})
        assert failed.status_code == 502
        assert "api.tomtom.com" not in failed.text and "key=" not in failed.text
        registry = client.get("/live-datasets").json()
        entry = next(item for item in registry["datasets"] if item["dataset_id"] == "tomtom_traffic_flow_segments")
        assert entry["status"] == "UNAVAILABLE"
    finally:
        main.app.dependency_overrides.pop(main.get_identity, None)
        main.traffic_observation_service, main.traffic_last_verified_at, main.traffic_verified_tiles, main.traffic_last_fetch_error = old
