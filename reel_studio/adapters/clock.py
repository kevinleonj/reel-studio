"""The only reader of the wall clock (scanner rule R11); everything else asks the Clock port."""

from datetime import UTC, datetime


class SystemClock:
    """Implements the Clock port with the real time, always timezone-aware UTC."""

    def now(self) -> datetime:
        return datetime.now(tz=UTC)
