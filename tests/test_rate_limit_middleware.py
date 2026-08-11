from fastapi.testclient import TestClient

import main


def test_health_endpoints_are_exempt_from_rate_limiting():
    main.rate_limiter.reset()
    main.rate_limiter.max_requests = 1
    client = TestClient(main.app)
    for _ in range(5):
        resp = client.get("/health")
        assert resp.status_code == 200
    main.rate_limiter.max_requests = int(__import__("os").environ.get("RATE_LIMIT_MAX_REQUESTS", "120"))


def test_requests_over_the_limit_get_429():
    main.rate_limiter.reset()
    original_max = main.rate_limiter.max_requests
    main.rate_limiter.max_requests = 3
    try:
        client = TestClient(main.app)
        for _ in range(3):
            resp = client.get("/runtime/identity")
            assert resp.status_code == 200
        blocked = client.get("/runtime/identity")
        assert blocked.status_code == 429
        assert "retry_after_seconds" in blocked.json()
        assert "Retry-After" in blocked.headers
    finally:
        main.rate_limiter.max_requests = original_max
        main.rate_limiter.reset()


def test_different_actors_get_independent_limits():
    main.rate_limiter.reset()
    original_max = main.rate_limiter.max_requests
    main.rate_limiter.max_requests = 1
    try:
        client = TestClient(main.app)
        token_a, _ = main.auth_service.issue_token("actor-a", [])
        token_b, _ = main.auth_service.issue_token("actor-b", [])

        r1 = client.get("/canonical-repository/documents", headers={"Authorization": f"Bearer {token_a}"})
        assert r1.status_code == 200
        r2 = client.get("/canonical-repository/documents", headers={"Authorization": f"Bearer {token_a}"})
        assert r2.status_code == 429

        # A different actor has an independent bucket, even from the same client.
        r3 = client.get("/canonical-repository/documents", headers={"Authorization": f"Bearer {token_b}"})
        assert r3.status_code == 200
    finally:
        main.rate_limiter.max_requests = original_max
        main.rate_limiter.reset()


def test_rate_limiter_is_configured_from_env_vars(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_MAX_REQUESTS", "42")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "7")
    from middleware.rate_limiter import SlidingWindowRateLimiter
    import os
    limiter = SlidingWindowRateLimiter(
        max_requests=int(os.environ["RATE_LIMIT_MAX_REQUESTS"]),
        window_seconds=float(os.environ["RATE_LIMIT_WINDOW_SECONDS"]),
    )
    assert limiter.max_requests == 42
    assert limiter.window_seconds == 7.0
