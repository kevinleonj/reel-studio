"""A transaction that runs out of attempts on a contended order is OrderBusy, which the API
answers with 503 and Retry-After, not a bare 500 (STEP-07 review round 1)."""

from collections.abc import Callable
from typing import Any

import pytest
from google.api_core import exceptions as gexc
from google.cloud import firestore

from reel_studio.adapters.orders_firestore import FirestoreOrders
from reel_studio.core.errors import OrderBusy
from tests.contract.test_orders import LIMITS, START
from tests.fakes.clock import FrozenClock


class NoClient:
    """Enough of a Firestore client for `_transaction`; the body never runs."""

    def transaction(self, **_: Any) -> object:
        return object()

    def collection(self, _name: str) -> "NoClient":
        return self

    def document(self, _name: str) -> object:
        return object()


def exhausted(_body: Callable[..., object]) -> Callable[[object], object]:
    def run(_tx: object) -> object:
        try:
            raise gexc.Aborted("Transaction lock timeout.")  # type: ignore[no-untyped-call]
        except gexc.Aborted as last:
            # What google-cloud-firestore raises once every attempt is used (transaction.py).
            raise ValueError("Failed to commit transaction in 12 attempts.") from last

    return run


def other_failure(_body: Callable[..., object]) -> Callable[[object], object]:
    def run(_tx: object) -> object:
        raise ValueError("not a contention failure")

    return run


def store() -> FirestoreOrders:
    client: Any = NoClient()  # Any: a stand-in for firestore.Client
    return FirestoreOrders(client, FrozenClock(START), LIMITS, timeout_s=1, max_attempts=12)


def test_exhausted_attempts_are_order_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(firestore, "transactional", exhausted)
    with pytest.raises(OrderBusy):
        store().reserve_uploads(
            f"{1:032x}", files=[{"name": "a.mp4", "size": 1}], max_files=2, max_bytes=10
        )


def test_other_value_errors_still_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(firestore, "transactional", other_failure)
    with pytest.raises(ValueError, match="not a contention failure"):
        store().reserve_uploads(
            f"{1:032x}", files=[{"name": "a.mp4", "size": 1}], max_files=2, max_bytes=10
        )
