"""
Session-wide test fixtures.

`main.app` is a module-level singleton reused by every test file's
`TestClient(main.app)` — that's fine for the request-handling stack
itself, but any middleware holding its own state (the rate limiter) needs
resetting between tests, or request counts silently accumulate across the
whole suite and tests start failing based on run order/count rather than
their own logic. Individual test files already do this per-service
(`main.bcaes_registry_service = main.BCAESRegistryService()` etc.) for
things they construct; the rate limiter is shared infrastructure every
test touches whether it's testing rate limiting or not, so it gets one
autouse fixture here instead of being repeated in every file.
"""
import pytest

import main


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    main.rate_limiter.reset()
    yield
