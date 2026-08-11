"""
Tests for InsightBridgeClient.

IMPORTANT SCOPE NOTE: this sandbox's network egress is restricted to an
allowlist that does NOT include onrender.com (see the repo's own network
configuration) — so these tests CANNOT make a real live call to
InsightBridge, unlike scripts/capture_*_evidence.py's live TestClient
calls against MASTERDB itself. What's tested here: unconfigured behavior
(real, no mocking needed) and request/response handling against a
monkeypatched httpx.get/post (verifies the client builds the right
request and handles success/error responses correctly — NOT a live
network round-trip). A real live-reachability check was done via the
web_fetch tool in conversation, separately from this test suite; see
CONSTITUTIONAL_RUNTIME_DEFINITION.md SS4 for that finding.
"""
import httpx
import pytest

from services.insightbridge_client import InsightBridgeClient, InsightBridgeUnavailableError


def test_unconfigured_raises_on_health_check(monkeypatch):
    monkeypatch.delenv("PRAVAH_BHIV_INSIGHT_FLOW_BRIDGE", raising=False)
    client = InsightBridgeClient()
    assert client.is_configured() is False
    with pytest.raises(InsightBridgeUnavailableError):
        client.health_check()


def test_unconfigured_raises_on_ingest(monkeypatch):
    monkeypatch.delenv("PRAVAH_BHIV_INSIGHT_FLOW_BRIDGE", raising=False)
    client = InsightBridgeClient()
    with pytest.raises(InsightBridgeUnavailableError):
        client.ingest(source="masterdb", metric_type="registry_summary", data={})


def test_configured_via_constructor_arg():
    client = InsightBridgeClient(base_url="https://example-insightbridge.test")
    assert client.is_configured() is True


def test_health_check_success(monkeypatch):
    client = InsightBridgeClient(base_url="https://example-insightbridge.test")

    def fake_get(url, timeout):
        assert url == "https://example-insightbridge.test/health"
        return httpx.Response(200, json={"status": "ok"}, request=httpx.Request("GET", url))

    monkeypatch.setattr("services.insightbridge_client.httpx.get", fake_get)
    result = client.health_check()
    assert result == {"status": "ok"}


def test_health_check_http_error(monkeypatch):
    client = InsightBridgeClient(base_url="https://example-insightbridge.test")

    def fake_get(url, timeout):
        request = httpx.Request("GET", url)
        return httpx.Response(503, text="Service Unavailable", request=request)

    monkeypatch.setattr("services.insightbridge_client.httpx.get", fake_get)
    with pytest.raises(InsightBridgeUnavailableError):
        client.health_check()


def test_ingest_success_sends_expected_envelope(monkeypatch):
    client = InsightBridgeClient(base_url="https://example-insightbridge.test")
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return httpx.Response(200, json={"accepted": True}, request=httpx.Request("POST", url))

    monkeypatch.setattr("services.insightbridge_client.httpx.post", fake_post)
    result = client.ingest(source="masterdb", metric_type="registry_summary", data={"product": 1})

    assert result == {"accepted": True}
    assert captured["url"] == "https://example-insightbridge.test/ingest"
    assert captured["json"]["source"] == "masterdb"
    assert captured["json"]["metric_type"] == "registry_summary"
    assert captured["json"]["data"] == {"product": 1}
    assert "timestamp" in captured["json"]


def test_ingest_connection_error_wrapped(monkeypatch):
    client = InsightBridgeClient(base_url="https://example-insightbridge.test")

    def fake_post(url, json, timeout):
        raise httpx.ConnectError("connection refused", request=httpx.Request("POST", url))

    monkeypatch.setattr("services.insightbridge_client.httpx.post", fake_post)
    with pytest.raises(InsightBridgeUnavailableError):
        client.ingest(source="masterdb", metric_type="x", data={})


def test_env_var_matches_ecosystem_naming(monkeypatch):
    """Uses the real ecosystem env var name (PRAVAH_BHIV_INSIGHT_FLOW_BRIDGE,
    shared 6 Aug 2026), not an invented one — so this plugs in directly
    once that variable is actually set in this environment."""
    monkeypatch.setenv("PRAVAH_BHIV_INSIGHT_FLOW_BRIDGE", "https://from-env.test")
    client = InsightBridgeClient()
    assert client.base_url == "https://from-env.test"
