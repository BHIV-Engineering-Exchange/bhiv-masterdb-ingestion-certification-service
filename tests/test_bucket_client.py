import os
from unittest.mock import MagicMock, patch

import httpx
import pytest

from services.bucket_client import BucketClient, BucketUnavailableError


def test_bucket_client_unconfigured_returns_not_configured():
    client = BucketClient(base_url="")
    assert client.is_configured() is False
    status = client.status()
    assert status["configured"] is False
    assert status["base_url"] == "NOT_CONFIGURED"


def test_bucket_client_configured_returns_configured():
    client = BucketClient(base_url="https://bucket.example.com", timeout_seconds=5.0)
    assert client.is_configured() is True
    status = client.status()
    assert status["configured"] is True
    assert status["base_url"] == "https://bucket.example.com"


def test_store_evidence_when_unconfigured_raises():
    client = BucketClient(base_url="")
    with pytest.raises(BucketUnavailableError, match="not configured"):
        client.store_evidence("ev-1", {"data": "test"})


def test_get_evidence_when_unconfigured_raises():
    client = BucketClient(base_url="")
    with pytest.raises(BucketUnavailableError, match="not configured"):
        client.get_evidence("ev-1")


def test_store_provenance_when_unconfigured_raises():
    client = BucketClient(base_url="")
    with pytest.raises(BucketUnavailableError, match="not configured"):
        client.store_provenance("ds-1", {"lineage": "test"})


def test_get_provenance_when_unconfigured_raises():
    client = BucketClient(base_url="")
    with pytest.raises(BucketUnavailableError, match="not configured"):
        client.get_provenance("ds-1")


def test_store_evidence_makes_post_request():
    client = BucketClient(base_url="https://bucket.example.com")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"stored": True, "evidence_id": "ev-1"}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.request.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = client.store_evidence("ev-1", {"payload": "data"})

        assert result["stored"] is True
        call_args = mock_client.request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "https://bucket.example.com/evidence"


def test_get_evidence_makes_get_request():
    client = BucketClient(base_url="https://bucket.example.com")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"evidence_id": "ev-1", "data": "value"}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.request.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = client.get_evidence("ev-1")

        assert result["evidence_id"] == "ev-1"
        call_args = mock_client.request.call_args
        assert call_args[0][0] == "GET"
        assert call_args[0][1] == "https://bucket.example.com/evidence/ev-1"


def test_bucket_client_uses_api_key_from_env(monkeypatch):
    monkeypatch.setenv("BUCKET_API_KEY", "secret-key-123")
    client = BucketClient(base_url="https://bucket.example.com")
    headers = client._headers()
    assert headers["X-API-Key"] == "secret-key-123"


def test_bucket_client_handles_http_error():
    client = BucketClient(base_url="https://bucket.example.com")
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Server Error", request=MagicMock(), response=mock_response
    )

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.request.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(BucketUnavailableError, match="500"):
            client.store_evidence("ev-1", {})


def test_bucket_client_handles_connect_error():
    client = BucketClient(base_url="https://bucket.example.com")

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.request.side_effect = httpx.ConnectError("Connection refused")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(BucketUnavailableError, match="Connection refused"):
            client.get_evidence("ev-1")
