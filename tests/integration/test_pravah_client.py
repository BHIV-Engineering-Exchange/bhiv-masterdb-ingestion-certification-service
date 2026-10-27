"""
Integration tests for Pravah Client Adapter and Circuit Breaker (T-GOV-002).
"""
from unittest.mock import MagicMock, patch
import pytest
import requests

from integrations.pravah_client import PravahClient
from middleware.circuit_breaker import CircuitBreakerState
from models_pravah import PravahEvent, PravahEventType


def test_pravah_client_simulated_mode():
    client = PravahClient(endpoint="")
    assert not client.is_configured()

    event = PravahEvent(
        event_id="cli-sim-01",
        event_type=PravahEventType.INGESTION_REQUESTED,
        entity_id="pkg-cli-01",
    )
    resp = client.publish_event(event)

    assert resp.simulated is True
    assert resp.status == "published_simulated"
    assert resp.event_id == "cli-sim-01"
    assert len(client.get_published_events()) == 1


@patch("requests.post")
def test_pravah_client_live_dispatch(mock_post):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "status": "published",
        "partition": 2,
    }

    client = PravahClient(endpoint="https://pravah.example.test")
    assert client.is_configured()

    event = PravahEvent(
        event_id="cli-live-01",
        event_type=PravahEventType.CERTIFICATION_GRANTED,
        entity_id="pkg-cli-02",
    )
    resp = client.publish_event(event)

    assert resp.status == "published"
    assert resp.partition == 2
    assert resp.simulated is False
    mock_post.assert_called_once()


@patch("requests.post")
def test_pravah_client_circuit_breaker_opens_on_failures(mock_post):
    mock_post.side_effect = requests.ConnectionError("Connection refused to Pravah bus")

    client = PravahClient(endpoint="https://pravah-failing.test")
    client._circuit_breaker.failure_threshold = 2

    event = PravahEvent(
        event_id="cli-fail-01",
        event_type=PravahEventType.INGESTION_REQUESTED,
        entity_id="pkg-cli-fail",
    )

    # 1st failure
    with pytest.raises(requests.ConnectionError):
        client.publish_event(event)

    # 2nd failure
    with pytest.raises(requests.ConnectionError):
        client.publish_event(event)

    assert client._circuit_breaker.state == CircuitBreakerState.OPEN

    # 3rd attempt while open returns fallback response without raising connection error
    resp = client.publish_event(event)
    assert resp.status == "circuit_breaker_open"
    assert resp.simulated is True
