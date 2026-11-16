"""In-memory rate limiting (§8.8: rate limit per device).

A token bucket per key: `capacity` requests, refilled evenly over `period_s`. Kept in the
process, which is enough for the one web instance in M1; M4 moves it to shared storage.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    at: float


class RateLimiter:
    def __init__(
        self,
        capacity: int,
        period_s: float,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 100_000,
    ) -> None:
        self.capacity = capacity
        self.rate = capacity / period_s  # tokens per second
        self.clock = clock
        self.max_keys = max_keys
        self._buckets: dict[str, _Bucket] = {}

    def hit(self, key: str) -> float | None:
        """Take one token for `key`. None if allowed, else the seconds until the next token."""
        now = self.clock()
        b = self._buckets.get(key)
        if b is None:
            if len(self._buckets) >= self.max_keys:
                self._prune(now)
            b = self._buckets[key] = _Bucket(float(self.capacity), now)
        else:
            b.tokens = min(self.capacity, b.tokens + (now - b.at) * self.rate)
            b.at = now
        if b.tokens >= 1:
            b.tokens -= 1
            return None
        return (1 - b.tokens) / self.rate

    def _prune(self, now: float) -> None:
        """Drop buckets that have refilled completely: they behave exactly like a new one."""
        full = self.capacity / self.rate
        self._buckets = {k: b for k, b in self._buckets.items() if now - b.at < full}


def retry_after_header(wait_s: float) -> str:
    return str(max(1, math.ceil(wait_s)))
