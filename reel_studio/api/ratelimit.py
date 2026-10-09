"""Per-address rate limits in memory (ARCHITECTURE.md §7: at most 2 instances, no shared store)."""

import threading
from collections import deque
from datetime import datetime, timedelta

from reel_studio.core.ports import Clock

WINDOW = timedelta(minutes=1)


class SlidingWindow:
    """At most `limit` calls per address in any rolling minute."""

    def __init__(self, limit: int, clock: Clock) -> None:
        self._limit = limit
        self._clock = clock
        self._calls: dict[str, deque[datetime]] = {}
        self._lock = threading.Lock()

    def allow(self, address: str) -> bool:
        now = self._clock.now()
        with self._lock:
            calls = self._calls.setdefault(address, deque())
            while calls and now - calls[0] >= WINDOW:
                calls.popleft()
            if not calls:
                del self._calls[address]  # an address seen once is not kept forever
                calls = self._calls.setdefault(address, deque())
            if len(calls) >= self._limit:
                return False
            calls.append(now)
            return True
