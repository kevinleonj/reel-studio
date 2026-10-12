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


class InFlight:
    """Keys with a request under way. `enter` never waits: a second request for the same key
    is refused at once instead of holding a worker thread on a contended record (review)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._keys: set[str] = set()

    def enter(self, key: str) -> bool:
        with self._lock:
            if key in self._keys:
                return False
            self._keys.add(key)
            return True

    def leave(self, key: str) -> None:
        with self._lock:
            self._keys.discard(key)
