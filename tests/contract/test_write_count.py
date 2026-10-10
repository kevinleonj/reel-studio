"""Assumption A5 (docs/ARCHITECTURE.md §4): Firestore writes for one order, counted on the emulator
over the whole life of a Stripe order (checkout to feedback). Every write of the adapter goes
through `Transaction.set` or `Transaction.create`, so counting those counts the writes."""

from collections.abc import Callable
from datetime import timedelta

import pytest
from google.cloud import firestore

from reel_studio.core.ports import NewOrder
from tests.contract.firestore_emulator import emulator_orders
from tests.contract.test_orders import LIMITS, SETTINGS, START
from tests.fakes.clock import FrozenClock

pytestmark = pytest.mark.emulator

STAGES = ("reading", "planning", "rendering", "checking", "saving")  # voice off, no revising
MEASURED_WRITES = 19  # first run 10 Oct 2026, recorded in docs/FACTS.md (F312, A5)


def test_writes_for_one_order(monkeypatch: pytest.MonkeyPatch) -> None:
    writes: list[str] = []

    def counted(name: str, real: Callable[..., object]) -> Callable[..., object]:
        def wrapper(self: firestore.Transaction, *args: object, **kwargs: object) -> object:
            writes.append(name)
            return real(self, *args, **kwargs)

        return wrapper

    monkeypatch.setattr(firestore.Transaction, "set", counted("set", firestore.Transaction.set))
    monkeypatch.setattr(
        firestore.Transaction, "create", counted("create", firestore.Transaction.create)
    )
    clock = FrozenClock(START)
    order_id = "a" * 32
    with emulator_orders(clock, LIMITS) as store:
        store.create_awaiting_payment(
            NewOrder(order_id, "hash", SETTINGS, "", START + timedelta(minutes=31))
        )
        store.set_checkout(order_id, session_id="cs_test_1")
        store.mark_paid(order_id, {"session_id": "cs_test_1", "email": "ana@example.test"})
        store.claim_email(order_id, "link")
        store.set_manifest(order_id, files=[{"name": "a.mp4", "size": 1}], bytes_declared=1)
        store.queue(order_id)
        assert store.take_slot(order_id)
        for stage in STAGES:
            store.set_stage(order_id, name=stage)
        store.finish(order_id, result={"versions": []}, cost={"usd_total": "0.95"})
        store.claim_email(order_id, "ready")
        store.mark_viewed(order_id)
        store.set_feedback(order_id, rating=5, comment="")
    assert len(writes) == MEASURED_WRITES, writes
