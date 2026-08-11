from middleware.rate_limiter import SlidingWindowRateLimiter


def test_allows_up_to_max_requests():
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60)
    assert limiter.allow("k", now=0) is True
    assert limiter.allow("k", now=1) is True
    assert limiter.allow("k", now=2) is True
    assert limiter.allow("k", now=3) is False


def test_different_keys_are_independent():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    assert limiter.allow("a", now=0) is True
    assert limiter.allow("b", now=0) is True
    assert limiter.allow("a", now=1) is False
    assert limiter.allow("b", now=1) is False


def test_old_requests_age_out_of_the_window():
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=10)
    assert limiter.allow("k", now=0) is True
    assert limiter.allow("k", now=1) is True
    assert limiter.allow("k", now=2) is False
    # first request (t=0) ages out once we're past t=10
    assert limiter.allow("k", now=11) is True


def test_retry_after_seconds_reflects_oldest_request_in_window():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=10)
    limiter.allow("k", now=0)
    assert limiter.retry_after_seconds("k", now=3) == 7.0


def test_retry_after_seconds_zero_for_unknown_key():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=10)
    assert limiter.retry_after_seconds("nope", now=0) == 0.0


def test_reset_clears_all_state():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    limiter.allow("k", now=0)
    assert limiter.allow("k", now=1) is False
    limiter.reset()
    assert limiter.allow("k", now=2) is True
