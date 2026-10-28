from fastapi.testclient import TestClient

import main
from auth.models import AuthIdentity
from integrations.adsb_military_connector import normalize_aircraft
from services.aircraft_observation_service import AircraftObservationService
from services.artifact_store import ArtifactStore
from services.source_registry_service import SourceRegistryService


def raw_aircraft(hex_id="AE1234", now=1_792_743_000):
    return {
        "hex": hex_id.lower(), "flight": "TEST123 ", "lat": 25.7, "lon": -80.2,
        "alt_baro": 10000, "gs": 250.5, "track": 90.2, "r": "TEST-1", "t": "C130",
    }, now


def test_normalizes_aircraft_and_preserves_missing_optional_fields():
    raw, now = raw_aircraft()
    normalized = normalize_aircraft(raw, "2026-10-23T09:00:00+00:00")
    assert normalized["aircraft_hex_id"] == "AE1234"
    assert normalized["callsign"] == "TEST123"
    assert normalized["ground_speed_kts"] == 250.5
    raw.pop("gs")
    assert "ground_speed_kts" not in normalize_aircraft(raw, None)


def test_skips_missing_coordinates_and_keeps_distinct_observation_times(tmp_path):
    raw, _ = raw_aircraft()
    assert normalize_aircraft({"hex": "AE1234"}, None) is None
    service = AircraftObservationService(ArtifactStore(str(tmp_path)))
    first = normalize_aircraft(raw, "2026-10-23T09:00:00+00:00")
    second = normalize_aircraft(raw, "2026-10-23T09:01:00+00:00")
    assert service.ingest({"source": "adsb.lol", "observations": [first]})["inserted"] == 1
    assert service.ingest({"source": "adsb.lol", "observations": [first]})["updated"] == 1
    assert service.ingest({"source": "adsb.lol", "observations": [second]})["inserted"] == 1
    assert len(service.list()) == 2


def test_api_ingests_and_reads_aircraft(monkeypatch, tmp_path):
    previous = main.aircraft_observation_service
    previous_registry = main.source_registry_service
    previous_feed_state = main.observation_feed_state["adsb_military"]
    main.aircraft_observation_service = AircraftObservationService(ArtifactStore(str(tmp_path)))
    main.source_registry_service = SourceRegistryService(store_dir=str(tmp_path / "registry"))
    main.observation_feed_state["adsb_military"] = {"status": "PENDING", "last_verified_at_utc": None}
    raw, _ = raw_aircraft()
    record = normalize_aircraft(raw, "2026-10-23T09:00:00+00:00")
    monkeypatch.setattr(main, "fetch_military_aircraft", lambda: {"source": "adsb.lol", "observations": [record]})
    main.app.dependency_overrides[main.get_identity] = lambda: AuthIdentity(actor="test", roles=["operator"])
    try:
        client = TestClient(main.app)
        response = client.post("/aircraft/adsb/military/ingest")
        assert response.status_code == 200
        assert response.json()["inserted"] == 1
        assert response.json()["status"] == "LIVE_VERIFIED"
        assert response.json()["readback_records"] == 1
        assert response.json()["registry_readback"] is True
        listed = client.get("/aircraft/adsb/military/observations")
        assert listed.status_code == 200
        assert listed.json()["observations"][0]["aircraft_hex_id"] == "AE1234"
        source = main.source_registry_service.get_source("src-gev-adsb-military")
        assert source.provenance_reference["last_fetch_status"] == "LIVE_VERIFIED"
    finally:
        main.app.dependency_overrides.pop(main.get_identity, None)
        main.aircraft_observation_service = previous
        main.source_registry_service = previous_registry
        main.observation_feed_state["adsb_military"] = previous_feed_state


def test_empty_adsb_snapshot_stays_pending(monkeypatch, tmp_path):
    previous = (main.aircraft_observation_service, main.source_registry_service,
                main.observation_feed_state["adsb_military"])
    main.aircraft_observation_service = AircraftObservationService(ArtifactStore(str(tmp_path / "aircraft")))
    main.source_registry_service = SourceRegistryService(store_dir=str(tmp_path / "registry"))
    main.observation_feed_state["adsb_military"] = {"status": "PENDING", "last_verified_at_utc": None}
    monkeypatch.setattr(main, "fetch_military_aircraft", lambda: {
        "source": "adsb.lol", "observations": [],
    })
    main.app.dependency_overrides[main.get_identity] = lambda: AuthIdentity(actor="test", roles=["operator"])
    try:
        response = TestClient(main.app).post("/aircraft/adsb/military/ingest")
        assert response.status_code == 200
        assert response.json()["status"] == "PENDING"
        source = main.source_registry_service.get_source("src-gev-adsb-military")
        assert source.provenance_reference["last_fetch_status"] == "PENDING"
    finally:
        main.app.dependency_overrides.pop(main.get_identity, None)
        (main.aircraft_observation_service, main.source_registry_service,
         main.observation_feed_state["adsb_military"]) = previous
