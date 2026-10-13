"""
Rate limiting ASGI middleware.

Keyed by the caller's actor (extracted from a Bearer JWT if present and
valid — best-effort, not re-validated for signature here since that's
already `auth/dependencies.py`'s job downstream; an invalid/expired token
just falls back to IP-based keying) or client IP otherwise. Health,
readiness, metrics, and docs endpoints are exempt — rate-limiting your
own health check is how you turn a monitoring system into an outage.

Config via env vars:
    RATE_LIMIT_MAX_REQUESTS   default 120
    RATE_LIMIT_WINDOW_SECONDS default 60

See middleware/rate_limiter.py's module docstring for the single-process/
not-distributed-safe caveat — that applies here unchanged.
"""
import os
from typing import Any, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from middleware.rate_limiter import SlidingWindowRateLimiter

_EXEMPT_PATHS = {"/health", "/ready", "/metrics", "/docs", "/openapi.json", "/redoc"}


def _extract_key(request: Request, auth_service: Optional[Any] = None) -> str:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if token:
            try:
                active_auth = auth_service
                if active_auth is None:
                    # Resolve active auth_service from request app state or main module
                    app = getattr(request, "app", None)
                    if app is not None:
                        active_auth = getattr(app.state, "auth_service", None)
                    if active_auth is None:
                        import main
                        active_auth = getattr(main, "auth_service", None)
                if active_auth is not None:
                    identity = active_auth.decode_token(token)
                    if identity.actor:
                        return f"actor:{identity.actor}"
            except Exception:
                # Token is invalid, malformed, expired, forged, or unverified.
                # Never trust unverified claims for rate-limit keying.
                # Fall back safely to client IP so forged tokens cannot
                # impersonate or exhaust another actor's rate-limit bucket.
                pass
    client = request.client
    return f"ip:{client.host}" if client else "ip:unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        limiter: SlidingWindowRateLimiter = None,
        auth_service: Optional[Any] = None,
    ) -> None:
        super().__init__(app)
        self.limiter = limiter or SlidingWindowRateLimiter(
            max_requests=int(os.environ.get("RATE_LIMIT_MAX_REQUESTS", "120")),
            window_seconds=float(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60")),
        )
        self.auth_service = auth_service

    async def dispatch(self, request: Request, call_next):
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        active_auth = self.auth_service
        if active_auth is None:
            app = getattr(request, "app", None)
            if app is not None:
                active_auth = getattr(app.state, "auth_service", None)

        key = _extract_key(request, auth_service=active_auth)
        if not self.limiter.allow(key):
            retry_after = self.limiter.retry_after_seconds(key)
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded.",
                    "retry_after_seconds": round(retry_after, 1),
                },
                headers={"Retry-After": str(int(retry_after) + 1)},
            )
        return await call_next(request)
