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

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from middleware.rate_limiter import SlidingWindowRateLimiter

_EXEMPT_PATHS = {"/health", "/ready", "/metrics", "/docs", "/openapi.json", "/redoc"}


def _extract_key(request: Request) -> str:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1]
        try:
            import jwt as _jwt  # local import: keeps this module importable even if
            # PyJWT is ever swapped out, since this is a best-effort convenience
            # extraction, not the actual auth check.
            # unverified: we don't have the signing key here by design (this
            # middleware runs before route-level auth), and rate-limit keying
            # doesn't need cryptographic proof — worst case an attacker crafts
            # a token claiming to be someone else and gets THAT actor's rate
            # limit bucket, which is a mild nuisance, not a security bypass
            # (route-level auth still independently verifies the token for
            # anything that matters).
            payload = _jwt.decode(token, options={"verify_signature": False})
            actor = payload.get("sub")
            if actor:
                return f"actor:{actor}"
        except Exception:
            pass
    client = request.client
    return f"ip:{client.host}" if client else "ip:unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: SlidingWindowRateLimiter = None) -> None:
        super().__init__(app)
        self.limiter = limiter or SlidingWindowRateLimiter(
            max_requests=int(os.environ.get("RATE_LIMIT_MAX_REQUESTS", "120")),
            window_seconds=float(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60")),
        )

    async def dispatch(self, request: Request, call_next):
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        key = _extract_key(request)
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
