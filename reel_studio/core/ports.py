"""The only doors to the outside world (docs/ARCHITECTURE.md §3).

Each port has a fake (tests), a local adapter and a cloud adapter; method names are binding.
Argument and return types marked "settles in STEP-NN" are refined by the lane that builds the
first adapter, in this file.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol, TypedDict

from reel_studio.core.errors import ErrorCode

# Payload shapes settle with their first adapter (STEP-03 for Claude and Gemini, STEP-06 for the
# website ports). Until then a port speaks in plain mappings.
Record = Mapping[str, object]
UploadTarget = Record  # settles in STEP-06


@dataclass(frozen=True)
class NewOrder:
    """What the checkout knows when it creates an order (STEP-06; ARCHITECTURE.md §4)."""

    order_id: str  # 32 hex characters, our own random id
    token_hash: str  # the link token is never stored, only its hash (D18)
    settings: Record
    email: str  # "" when the user gave none (PAYMENTS=off)
    checkout_expires_at: datetime


@dataclass(frozen=True)
class QueueLimits:
    """The Orders adapters' share of config/limits.toml (D25, D52, D55)."""

    running_max: int
    lease_minutes: int
    weekly_cap: int
    paid_not_started_days: int
    # The sweep expires an unconfirmed checkout this long after it should have expired.
    expiry_grace_minutes: int


class SweepReport(TypedDict):
    failed: list[str]
    expired: list[str]
    abandoned: list[str]


class Storage(Protocol):
    def create_upload_session(self, order_id: str, file: Record) -> UploadTarget: ...
    def list_inputs(self, order_id: str) -> Sequence[Record]: ...
    def download(self, key: str, path: Path) -> None: ...
    def upload(self, path: Path, key: str, content_type: str) -> None: ...
    def signed_url(self, key: str, filename: str, minutes: int) -> str: ...
    def delete_order(self, order_id: str) -> None: ...


class Orders(Protocol):
    """Order documents and the global limits (ARCHITECTURE.md §4). Every transition is
    idempotent: calling it when the status already moved on changes nothing."""

    def create_awaiting_payment(self, order: NewOrder) -> str: ...  # raises WeekFull
    def mark_paid(self, order_id: str, stripe: Record) -> None: ...
    def expire(self, order_id: str) -> None: ...
    def set_manifest(
        self, order_id: str, *, files: Sequence[Record], bytes_declared: int
    ) -> None: ...
    def queue(self, order_id: str) -> None: ...  # raises ValueError unless paid
    def take_slot(self, order_id: str) -> bool: ...
    def release_slot(self, order_id: str) -> None: ...
    def next_queued(self) -> str | None: ...
    def set_stage(self, order_id: str, *, name: str) -> None: ...
    def finish(self, order_id: str, *, result: Record, cost: Record) -> None: ...
    def fail(self, order_id: str, *, code: ErrorCode) -> None: ...
    def pause(self, order_id: str, *, code: ErrorCode) -> None: ...
    def get(self, order_id: str) -> Record | None: ...


class OrderUpkeep(Protocol):
    """Order writes beyond ARCHITECTURE.md §3's binding list, added in STEP-06 for the result
    page and the sweep (§7). Same adapters as Orders."""

    def mark_viewed(self, order_id: str) -> None: ...
    def set_feedback(self, order_id: str, *, rating: int, comment: str) -> None: ...
    def mark_deleted(self, order_id: str) -> None: ...
    def sweep(self) -> SweepReport: ...
    def queue_position(self, order_id: str) -> int | None: ...  # orders ahead; None unless queued


class OrderStore(Orders, OrderUpkeep, Protocol):
    """What the API needs from one Orders adapter."""


class Launcher(Protocol):
    def launch(self, order_id: str) -> str: ...


class Mailer(Protocol):
    def send(self, template: str, to: str, data: Record) -> None: ...


class Payments(Protocol):
    def find_code(self, code: str) -> Record | None: ...
    def create_checkout(
        self, order_id: str, promo_id: str, urls: Record, expires_at: datetime
    ) -> Record: ...
    def parse_webhook(self, payload: bytes, signature: str) -> Record: ...
    def get_session(self, session_id: str) -> Record: ...


class Claude(Protocol):
    def count_tokens(self, request: Record) -> int: ...
    def create(self, request: Record) -> Record: ...


class Transcriber(Protocol):
    def transcribe(self, audio_path: Path, timestamps: bool = True) -> Record: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
