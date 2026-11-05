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
    adapter = MDUContractAdapter(client=MDUClient(base_url=None, api_key=None))
    assert adapter.is_live() is False


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


def test_fetch_provenance_resolves_canonical_dataset_id_before_lookup(monkeypatch):
    client = MDUClient(base_url="https://example-mdu.test", api_key="k")
    canonical_id = "BHIV-DS-MARITIME-AIS-LIVE-001"
    mdu_id = "6f84dede-43f4-488d-8bb4-c17f712d7e1a"
    requested_urls = []

    def fake_get(url, headers, timeout):
        requested_urls.append(url)
        if url.endswith(f"/api/v1/datasets/canonical/{canonical_id}"):
            return httpx.Response(
                200,
                json={"id": mdu_id},
                request=httpx.Request("GET", url),
            )
        if url.endswith(f"/api/v1/datasets/{mdu_id}/provenance"):
            return httpx.Response(
                200,
                json=[{"event_type": "ORIGIN"}],
                request=httpx.Request("GET", url),
            )
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr("services.mdu_client.httpx.get", fake_get)
    adapter = MDUContractAdapter(client=client)

    result = adapter.fetch_provenance_contract(canonical_id)

    assert result == [{"event_type": "ORIGIN"}]
    assert requested_urls == [
        f"https://example-mdu.test/api/v1/datasets/canonical/{canonical_id}",
        f"https://example-mdu.test/api/v1/datasets/{mdu_id}/provenance",
    ]


def test_gev_dataset_alias_resolves_mdu_schema_and_provenance(monkeypatch):
    client = MDUClient(base_url="https://example-mdu.test", api_key="k")
    adapter = MDUContractAdapter(client=client)
    mdu_canonical_id = "BHIV-DS-GEV-SEISMIC-EVENTS-001"
    mdu_id = "63bd8469-3a27-42b3-8c0a-847adbda6419"
    requested_urls = []

    def fake_get(url, headers, timeout):
        requested_urls.append(url)
        if url.endswith(f"/api/v1/datasets/canonical/{mdu_canonical_id}"):
            return httpx.Response(
                200,
                json={"id": mdu_id, "canonical_id": mdu_canonical_id},
                request=httpx.Request("GET", url),
            )
        if url.endswith(f"/api/v1/schemas/dataset/{mdu_id}"):
            return httpx.Response(
                200,
                json=[{"schema_version": "1.0.0"}],
                request=httpx.Request("GET", url),
            )
        if url.endswith(f"/api/v1/datasets/{mdu_id}/provenance"):
            return httpx.Response(
                200,
                json=[{"event_type": "ORIGIN", "source_system": "USGS"}],
                request=httpx.Request("GET", url),
            )
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr("services.mdu_client.httpx.get", fake_get)

    assert adapter.fetch_schema_contract("ds-gev-seismic-events") == {
        "schema_version": "1.0.0"
    }
    assert adapter.fetch_provenance_contract("ds-gev-seismic-events") == [
        {"event_type": "ORIGIN", "source_system": "USGS"}
    ]
    assert adapter.fetch_canonical_dataset("ds-gev-seismic-events") == {
        "id": mdu_id,
        "canonical_id": mdu_canonical_id,
    }
    assert requested_urls == [
        f"https://example-mdu.test/api/v1/datasets/canonical/{mdu_canonical_id}",
        f"https://example-mdu.test/api/v1/schemas/dataset/{mdu_id}",
        f"https://example-mdu.test/api/v1/datasets/{mdu_id}/provenance",
        f"https://example-mdu.test/api/v1/datasets/canonical/{mdu_canonical_id}",
    ]