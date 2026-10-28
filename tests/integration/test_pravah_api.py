"""
Integration tests for Pravah API endpoints and HTTP error boundaries (T-GOV-002).
"""
import pytest
from fastapi.testclient import TestClient

from main import app
from models import PackageStatus

client = TestClient(app)


def test_api_ingest_event_success():
    payload = {
        "event_id": "api-evt-01",
        "topic": "pravah.masterdb.events",
        "event_type": "INGESTION_REQUESTED",
        "entity_type": "package",
        "entity_id": "pkg-api-01",
        "producer": "api-test",
        "target_status": "INGESTED",
        "payload": {"source_verified": True},
    }
    resp = client.post("/pravah/events", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "COMMITTED"
    assert data["event_id"] == "api-evt-01"
    assert data["current_status"] == "INGESTED"
    assert len(data["state_hash"]) == 64


def test_api_ingest_event_malformed_input_returns_422_no_500():
    # Extra unexpected field (violates extra="forbid")
    payload = {
        "event_id": "api-evt-bad-01",
        "event_type": "INGESTION_REQUESTED",
        "entity_id": "pkg-api-bad",
        "unauthorized_field": "disallowed",
    }
    resp = client.post("/pravah/events", json=payload)
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data
    assert data["error"]["type"] == "validation_error"


def test_api_ingest_event_invalid_type_returns_422_no_500():
    # Non-string entity_id or invalid enum
    payload = {
        "event_id": "api-evt-bad-02",
        "event_type": "NOT_A_VALID_EVENT_TYPE",
        "entity_id": "pkg-api-bad",
    }
    resp = client.post("/pravah/events", json=payload)
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data


def test_api_ingest_event_invalid_transition_returns_422():
    # Attempt jumping from REGISTERED to ARCHIVED directly
    payload = {
        "event_id": "api-evt-illegal-01",
        "event_type": "STATUS_CHANGED",
        "entity_id": "pkg-api-illegal-01",
        "target_status": "ARCHIVED",
    }
    resp = client.post("/pravah/events", json=payload)
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data
    assert "Invalid transition" in data["error"]["message"]


def test_api_get_event_by_id():
    # Ingest event first
    client.post(
        "/pravah/events",
        json={
            "event_id": "api-evt-lookup-01",
            "event_type": "INGESTION_REQUESTED",
            "entity_id": "pkg-api-lookup-01",
            "target_status": "INGESTED",
            "payload": {"source_verified": True},
        },
    )

    resp = client.get("/pravah/events/api-evt-lookup-01")
    assert resp.status_code == 200
    entry = resp.json()
    assert entry["event"]["event_id"] == "api-evt-lookup-01"

    # Non-existent event returns 404
    resp_missing = client.get("/pravah/events/non-existent-id")
    assert resp_missing.status_code == 404


def test_api_query_ledger():
    resp = client.get("/pravah/ledger?limit=10")
    assert resp.status_code == 200
    entries = resp.json()
    assert isinstance(entries, list)


def test_api_get_entity_state():
    client.post(
        "/pravah/events",
        json={
            "event_id": "api-evt-state-01",
            "event_type": "INGESTION_REQUESTED",
            "entity_id": "pkg-api-state-01",
            "target_status": "INGESTED",
            "payload": {"source_verified": True},
        },
    )
    resp = client.get("/pravah/state/pkg-api-state-01")
    assert resp.status_code == 200
    data = resp.json()
    assert data["entity_id"] == "pkg-api-state-01"
    assert data["current_status"] == "INGESTED"
    assert len(data["state_hash"]) == 64


def test_api_pipeline_execute():
    payload = {
        "entity_id": "pkg-api-pipe-01",
        "initial_status": "REGISTERED",
        "target_status": "CERTIFIED",
        "context": {
            "source_verified": True,
            "schema_integrity": 0.99,
            "compliance_verified": True,
            "certification_score": 95.0,
        },
    }
    resp = client.post("/pipeline/execute", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["final_status"] == "CERTIFIED"
    assert len(data["transitions"]) == 4
    assert len(data["state_hash"]) == 64


def test_api_verify_determinism_endpoint():
    resp = client.post("/pravah/verify-determinism", json={"runs": 10})
    assert resp.status_code == 200
    data = resp.json()
    assert data["runs_completed"] == 10
    assert data["identical_hashes"] is True
    assert data["status"] == "PASS"
    assert len(data["final_hash"]) == 64
