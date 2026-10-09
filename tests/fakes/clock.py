"""A clock that only moves when the test says so."""

from datetime import datetime, timedelta


class FrozenClock:
    """Implements the Clock port; `now()` returns the same instant until `advance`."""

    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FrozenClock needs a timezone-aware datetime")
        self._at = at

    def now(self) -> datetime:
        return self._at

    def advance(self, by: timedelta) -> None:
        self._at += by
