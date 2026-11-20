"""Login failure limiter. Redis-backed for multi-replica API deployments,
with an in-process fallback when Redis is not configured (local/dev/tests).
"""
from __future__ import annotations

import time
import uuid


class LoginRateLimiter:
    def __init__(self, redis_url: str = "", max_failures: int = 5, window: int = 300):
        self.max_failures = max_failures
        self.window = window
        self._local: dict[str, list[float]] = {}
        self._redis = None
        if redis_url:
            try:
                import redis  # type: ignore[import-not-found]
                self._redis = redis.from_url(
                    redis_url, socket_connect_timeout=0.2, socket_timeout=0.2)
                self._redis.ping()
            except Exception:
                self._redis = None  # degrade gracefully to local limiter

    @property
    def backend(self) -> str:
        return "redis" if self._redis is not None else "local"

    def _key(self, login: str) -> str:
        return f"harness:login-fail:{login}"

    def allowed(self, login: str) -> bool:
        """False when the login has too many failures inside the window."""
        now = time.time()
        if self._redis is not None:
            try:
                key = self._key(login)
                pipe = self._redis.pipeline()
                pipe.zremrangebyscore(key, 0, now - self.window)
                pipe.zcard(key)
                pipe.expire(key, self.window)
                _, count, _ = pipe.execute()
                return int(count) < self.max_failures
            except Exception:
                self._redis = None  # fall back for the rest of this process
        attempts = [t for t in self._local.get(login, []) if now - t < self.window]
        self._local[login] = attempts
        return len(attempts) < self.max_failures

    def record_failure(self, login: str) -> None:
        now = time.time()
        if self._redis is not None:
            try:
                key = self._key(login)
                pipe = self._redis.pipeline()
                pipe.zadd(key, {f"{now}:{uuid.uuid4().hex}": now})
                pipe.expire(key, self.window)
                pipe.execute()
                return
            except Exception:
                self._redis = None
        self._local.setdefault(login, []).append(now)

    def clear(self, login: str) -> None:
        if self._redis is not None:
            try:
                self._redis.delete(self._key(login))
                return
            except Exception:
                self._redis = None
        self._local.pop(login, None)
