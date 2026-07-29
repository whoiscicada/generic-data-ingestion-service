"""Async token-bucket rate limiter, one instance per source.

Keeps the Fetcher within a source's configured requests_per_second/burst
regardless of how many pages it ends up paginating through.
"""

from __future__ import annotations

import asyncio
import time


class TokenBucketRateLimiter:
    def __init__(self, requests_per_second: float, burst: int):
        self.rate = requests_per_second
        self.capacity = float(burst)
        self._tokens = float(burst)
        self._updated_at = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._updated_at
                self._updated_at = now
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                wait_seconds = (1 - self._tokens) / self.rate
                await asyncio.sleep(wait_seconds)
