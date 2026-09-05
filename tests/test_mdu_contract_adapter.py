import httpx
import pytest

from middleware.circuit_breaker import CircuitBreakerState


from services.mdu_contract_adapter import MDUContractAdapter
from services.mdu_client import MDUClient


def test_negotiate_version_exact_match():
    result = MDUContractAdapter.negotiate_version("2.1", "2.1")
    assert result["compatible"] is True
    assert result["negotiation"] == "exact_match"


def test_negotiate_version_minor_drift_is_compatible():
    result = MDUContractAdapter.negotiate_version("2.1", "2.4")
    assert result["compatible"] is True
    assert result["negotiation"] == "minor_version_drift"


def test_negotiate_version_major_mismatch_is_incompatible():
    result = MDUContractAdapter.negotiate_version("1.9", "2.0")
    assert result["compatible"] is False
    assert result["negotiation"] == "major_version_mismatch"


def test_negotiate_version_missing_remote_version():
    result = MDUContractAdapter.negotiate_version("1.0", "")
    assert result["compatible"] is False
    assert result["negotiation"] == "unknown"


def test_schema_compatibility_falls_back_to_placeholder_when_unconfigured(monkeypatch):
    monkeypatch.delenv("MDU_BASE_URL", raising=False)
    monkeypatch.delenv("MDU_API_KEY", raising=False)
    adapter = MDUContractAdapter(client=MDUClient(base_url=None, api_key=None))
    result = adapter.validate_schema_compatibility(
        dataset_id="BHIV-DS-MARITIME-AIS-LIVE-001", local_schema_version="1.0"
    )
    assert result["source"] == "placeholder"
    assert result["compatible"] is True


def test_adapter_reports_not_live_when_unconfigured(monkeypatch):
    monkeypatch.delenv("MDU_BASE_URL", raising=False)
    monkeypatch.delenv("MDU_API_KEY", raising=False)


def test_circuit_breaker_opens_after_failures(monkeypatch):
    client = MDUClient(base_url="https://example-mdu.test", api_key="k")
    client._circuit_breaker.failure_threshold = 2

    def fake_get(url, headers, timeout):
        raise httpx.ConnectError("connection refused", request=httpx.Request("GET", url))

    monkeypatch.setattr("services.mdu_client.httpx.get", fake_get)

    with pytest.raises(Exception):
        client.get_dataset_schema("ds")

    with pytest.raises(Exception):
        client.get_dataset_schema("ds")

    assert client._circuit_breaker.state == CircuitBreakerState.OPEN

    adapter = MDUContractAdapter(client=MDUClient(base_url=None, api_key=None))
    assert adapter.is_live() is False