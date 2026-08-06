from fastapi.testclient import TestClient

import main


def test_replay_registry_manifest_is_public_and_honest():
    client = TestClient(main.app)
    resp = client.get("/replay-registry/manifest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service_name"] == "MASTERDB"
    assert body["status"] == "not_yet_registered"
    names = {c["name"] for c in body["replay_capabilities"]}
    assert "bcaes_registry_architecture" in names


def test_replay_registry_manifest_hash_matches_live_validation():
    client = TestClient(main.app)
    architecture = client.get("/bcaes/validate/architecture").json()
    manifest = client.get("/replay-registry/manifest").json()
    bcaes_entry = next(c for c in manifest["replay_capabilities"] if c["name"] == "bcaes_registry_architecture")
    assert bcaes_entry["current_replay_hash"] == architecture["replay_hash"]
