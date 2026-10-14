"""Lightweight in-process rate limiting for FastAPI routes.

Sliding-window counter per (bucket, client IP). No external store.

Limits are per process. If the service runs more than one replica,
the effective limit is per replica. See PR notes.

Client IP comes from the RIGHTMOST X-Forwarded-For entry. The edge proxy
appends the real client address, so the rightmost entry is the one it
set. Leftmost entries are client-supplied and can be spoofed.
Falls back to the socket peer when the header is absent.

Toggles (env):
  RATE_LIMIT_ENABLED        default "true". Set "false" to disable all limits.
  RATE_LIMIT_LOGIN_MAX      default 10 attempts
  RATE_LIMIT_LOGIN_WINDOW   default 60 seconds
  RATE_LIMIT_PUBLIC_MAX     default 60 requests
  RATE_LIMIT_PUBLIC_WINDOW  default 60 seconds
"""
import os
import threading
import time
from collections import deque
from typing import Callable, Deque, Dict

from fastapi import HTTPException, Request

MAX_TRACKED_KEYS = 10_000


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def rate_limit_enabled() -> bool:
    return os.environ.get("RATE_LIMIT_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


class SlidingWindowLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: Dict[str, Deque[float]] = {}

    def hit(self, key: str, limit: int, window: int) -> float:
        """Record one hit. Return 0.0 if allowed, else seconds until a slot frees."""
        now = self._clock()
        cutoff = now - window
        with self._lock:
            q = self._hits.get(key)
            if q is None:
                if len(self._hits) >= MAX_TRACKED_KEYS:
                    self._evict_expired(cutoff)
                if len(self._hits) >= MAX_TRACKED_KEYS:
                    # Fail closed under a key flood: refuse new keys.
                    return float(window)
                q = deque()
                self._hits[key] = q
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= limit:
                return max(0.0, q[0] + window - now)
            q.append(now)
            return 0.0

    def _evict_expired(self, cutoff: float) -> None:
        for k in list(self._hits.keys()):
            q = self._hits[k]
            while q and q[0] <= cutoff:
                q.popleft()
            if not q:
                del self._hits[k]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_limiter = SlidingWindowLimiter()


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def rate_limit(bucket: str, limit_env: str, window_env: str, default_limit: int, default_window: int):
    """Return a FastAPI dependency that enforces the limit for this bucket and client IP.

    Limits are read per request so tests and deploys can change env without reimport.
    """

    def dependency(request: Request) -> None:
        if not rate_limit_enabled():
            return None
        limit = _env_int(limit_env, default_limit)
        window = _env_int(window_env, default_window)
        key = f"{bucket}:{client_ip(request)}"
        retry_after = _limiter.hit(key, limit, window)
        if retry_after > 0:
            raise HTTPException(
                status_code=429,
                detail="Too many requests",
                headers={"Retry-After": str(int(retry_after) + 1)},
            )
        return None

    return dependency


login_rate_limit = rate_limit(
    "login", "RATE_LIMIT_LOGIN_MAX", "RATE_LIMIT_LOGIN_WINDOW", default_limit=10, default_window=60
)

public_rate_limit = rate_limit(
    "public", "RATE_LIMIT_PUBLIC_MAX", "RATE_LIMIT_PUBLIC_WINDOW", default_limit=60, default_window=60
)
