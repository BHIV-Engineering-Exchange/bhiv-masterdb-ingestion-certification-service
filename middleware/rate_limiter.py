"""
Sliding-window rate limiter — core logic, no FastAPI/ASGI dependency so
it's independently unit-testable.

SCOPE, STATED PLAINLY: this is in-memory, per-process. It works correctly
for a single worker process. It is NOT distributed-safe — if this service
ever runs with multiple worker processes or multiple instances behind a
load balancer (Render's `WEB_CONCURRENCY` env var, seen in this repo's
own deploy logs, defaults to more than 1 based on available CPUs), each
process enforces its own independent limit, so the *effective* combined
limit is (configured limit) × (worker count), not the configured limit.
A real distributed rate limiter needs a shared store (Redis, etc.) that
doesn't exist in this environment. This is stated here rather than
silently shipped as if it were the real thing.
"""
import time
from collections import defaultdict, deque
from typing import Deque, Dict


class SlidingWindowRateLimiter:
    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: Dict[str, Deque[float]] = defaultdict(deque)

    def allow(self, key: str, now: float = None) -> bool:
        """Returns True and records the request if under the limit; returns
        False (does not record) if the key is already at the limit within
        the current window."""
        now = now if now is not None else time.monotonic()
        window = self._requests[key]

        while window and now - window[0] > self.window_seconds:
            window.popleft()

        if len(window) >= self.max_requests:
            return False

        window.append(now)
        return True

    def retry_after_seconds(self, key: str, now: float = None) -> float:
        now = now if now is not None else time.monotonic()
        window = self._requests[key]
        if not window:
            return 0.0
        oldest = window[0]
        return max(0.0, self.window_seconds - (now - oldest))

    def reset(self) -> None:
        self._requests.clear()
