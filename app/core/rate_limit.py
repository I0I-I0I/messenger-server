from __future__ import annotations

import logging
import threading
from collections import defaultdict, deque
from time import monotonic

from fastapi import Request

from app.core.errors import APIError
from app.core.settings import get_settings

logger = logging.getLogger(__name__)


class InMemoryRateLimiter:
    def __init__(self, *, window_seconds: int, max_requests: int) -> None:
        self.window_seconds = window_seconds
        self.max_requests = max_requests
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        now = monotonic()
        with self._lock:
            events = self._events[key]
            cutoff = now - self.window_seconds
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.max_requests:
                return False
            events.append(now)
            return True


settings = get_settings()
auth_limiter = InMemoryRateLimiter(
    window_seconds=settings.auth_rate_limit_window_seconds,
    max_requests=settings.auth_rate_limit_max_requests,
)


def enforce_auth_rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    key = f"{client_ip}:{request.url.path}"
    logger.debug("Rate limit check key=%s", key)
    if not auth_limiter.hit(key):
        logger.warning("Rate limit exceeded for key=%s", key)
        raise APIError(status_code=429, code="rate_limited", message="Too many authentication requests")
