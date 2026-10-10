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
        self._pruned_at: datetime | None = None

    def allow(self, address: str) -> bool:
        now = self._clock.now()
        with self._lock:
            if self._pruned_at is None or now - self._pruned_at >= WINDOW:
                # Without this, every address that ever called would stay in memory.
                stale = [a for a, c in self._calls.items() if not c or now - c[-1] >= WINDOW]
                for gone in stale:
                    del self._calls[gone]
                self._pruned_at = now
            calls = self._calls.setdefault(address, deque())
            while calls and now - calls[0] >= WINDOW:
                calls.popleft()
            if len(calls) >= self._limit:
                return False
            calls.append(now)
            return True
