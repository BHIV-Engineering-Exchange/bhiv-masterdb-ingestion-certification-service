"""
Tests for CORS middleware on the FastAPI app.

Verifies:
- OPTIONS preflight requests return 200 with correct CORS headers.
- Non-OPTIONS requests from allowed origins include CORS headers.
- CORS_ALLOWED_ORIGINS env var controls the allowed-origins behaviour.
"""

import importlib
import os
import pytest
from fastapi.testclient import TestClient

import main as main_module


@pytest.fixture
def client() -> TestClient:
    return TestClient(main_module.app)


class TestCORSPreflight:
    """OPTIONS requests (preflight) should return 200 with CORS headers."""

    def test_preflight_returns_200(self, client: TestClient):
        """Default CORS_ALLOWED_ORIGINS=* - preflight succeeds and returns *."""
        resp = client.options(
            "/packages",
            headers={
                "Origin": "https://bhiv-gurukul.example.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization,Content-Type",
            },
        )
        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == "*"
        # allow_methods=["*"] is expanded by Starlette into the full method list.
        assert resp.headers["access-control-allow-methods"] == "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT"
        # allow_headers=["*"] means any requested header is mirrored back verbatim.
        assert resp.headers["access-control-allow-headers"] == "Authorization,Content-Type"
        # Expose-Headers is a simple-response header, not a preflight one — see
        # test_get_exposes_custom_headers below.

    def test_preflight_omits_credentials_header(self, client: TestClient):
        """auth is Bearer-JWT (Authorization header), not cookies, so
        allow_credentials=False and no allow-credentials header is sent —
        this is also what avoids the '*' + credentials mismatch that makes
        browsers block the actual (non-preflight) response even though the
        preflight itself succeeds."""
        resp = client.options(
            "/upload/jobs",
            headers={
                "Origin": "https://bhiv-aiac.example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.status_code == 200
        assert "access-control-allow-credentials" not in resp.headers


class TestCORSSimpleRequests:
    """GET/POST responses from allowed origins include CORS headers."""

    def test_get_includes_allow_origin(self, client: TestClient):
        """Any GET (200 or 4xx) should carry Access-Control-Allow-Origin."""
        resp = client.get("/packages", headers={"Origin": "https://bhiv-marine.example.com"})
        assert "access-control-allow-origin" in resp.headers
        assert resp.headers["access-control-allow-origin"] == "*"

    def test_get_exposes_custom_headers(self, client: TestClient):
        """X-Trace-Id and X-Request-Id should be listed in expose-headers."""
        resp = client.get(
            "/upload/jobs/upl-example",
            headers={"Origin": "https://bhiv-govt.example.com"},
        )
        assert "access-control-expose-headers" in resp.headers
        exposed = resp.headers["access-control-expose-headers"]
        assert "X-Trace-Id" in exposed


class TestCORSOriginRestriction:
    """CORS_ALLOWED_ORIGINS env var controls which origins are permitted."""

    def test_default_all_origins(self):
        """Default (no env var) should set _allowed_origins to ['*']."""
        os.environ.pop("CORS_ALLOWED_ORIGINS", None)
        importlib.reload(main_module)
        assert main_module._allowed_origins == ["*"]

    def test_explicit_origin_list(self):
        """CORS_ALLOWED_ORIGINS with specific origins should be parsed correctly."""
        os.environ["CORS_ALLOWED_ORIGINS"] = "https://bhiv-gurukul.example.com, https://bhiv-aiac.example.com"
        try:
            importlib.reload(main_module)
            assert "https://bhiv-gurukul.example.com" in main_module._allowed_origins
            assert "https://bhiv-aiac.example.com" in main_module._allowed_origins
            assert "*" not in main_module._allowed_origins
        finally:
            os.environ.pop("CORS_ALLOWED_ORIGINS", None)
            importlib.reload(main_module)

    def test_blank_env_value_falls_back_to_wildcard(self):
        """CORS_ALLOWED_ORIGINS="" (set but empty) must not silently collapse
        to an empty allow-list — that would reject every origin with no
        indication why. Blank is treated the same as unset."""
        os.environ["CORS_ALLOWED_ORIGINS"] = ""
        try:
            importlib.reload(main_module)
            assert main_module._allowed_origins == ["*"]
        finally:
            os.environ.pop("CORS_ALLOWED_ORIGINS", None)
            importlib.reload(main_module)


class TestCORSProductionOriginScenario:
    """Reproduces the reported production setup: CORS_ALLOWED_ORIGINS pinned
    to the deployed Vercel frontend's exact origin (no wildcard)."""

    PROD_ORIGIN = "https://masterdb-control-center.vercel.app"

    @pytest.fixture
    def prod_client(self):
        os.environ["CORS_ALLOWED_ORIGINS"] = self.PROD_ORIGIN
        try:
            importlib.reload(main_module)
            yield TestClient(main_module.app)
        finally:
            os.environ.pop("CORS_ALLOWED_ORIGINS", None)
            importlib.reload(main_module)

    def test_upload_preflight_from_allowed_origin_succeeds(self, prod_client: TestClient):
        """A real browser preflight (includes Access-Control-Request-Method)
        for POST /upload from the configured frontend origin must succeed."""
        resp = prod_client.options(
            "/upload",
            headers={
                "Origin": self.PROD_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization,Content-Type",
            },
        )
        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == self.PROD_ORIGIN
        assert "access-control-allow-credentials" not in resp.headers

    def test_databases_get_from_allowed_origin_includes_header(self, prod_client: TestClient):
        resp = prod_client.get("/databases", headers={"Origin": self.PROD_ORIGIN})
        assert resp.headers.get("access-control-allow-origin") == self.PROD_ORIGIN

    def test_request_from_other_origin_is_rejected(self, prod_client: TestClient):
        """An origin that isn't the configured frontend gets no
        Access-Control-Allow-Origin header on a simple request, and a 400
        'Disallowed CORS origin' on preflight — this is what a misconfigured
        or stale CORS_ALLOWED_ORIGINS value looks like from the outside."""
        other = "https://some-other-app.example.com"
        preflight = prod_client.options(
            "/upload",
            headers={
                "Origin": other,
                "Access-Control-Request-Method": "POST",
            },
        )
        assert preflight.status_code == 400

        simple = prod_client.get("/health", headers={"Origin": other})
        assert "access-control-allow-origin" not in simple.headers