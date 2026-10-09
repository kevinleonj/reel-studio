"""Contract for the OrderStore port (docs/ARCHITECTURE.md §4 rules), run against every adapter.

The fake runs in every `make test`; the Firestore adapter runs against the emulator
(`make test-emulator`, marker `emulator`). Both must pass the same cases.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from reel_studio.core.errors import ErrorCode, WeekFull
from reel_studio.core.ports import NewOrder, OrderStore, QueueLimits
from tests.contract.orders_adapters import ADAPTERS, OrdersFactory
from tests.fakes.clock import FrozenClock

START = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)  # a Monday, ISO week 2026-W42
LIMITS = QueueLimits(
    running_max=2,
    lease_minutes=70,
    weekly_cap=2,
    paid_not_started_days=7,
    expiry_grace_minutes=5,
    order_days=30,
)
SETTINGS = {
    "style": "recipe",
    "length_s": 30,
    "text_lang": "en",
    "keep_voice": False,
    "chips": [],
    "note": "",
}


@pytest.fixture(params=[pytest.param(a, marks=a.marks, id=a.name) for a in ADAPTERS])
def orders(request: pytest.FixtureRequest) -> Iterator[tuple[OrderStore, FrozenClock]]:
    factory: OrdersFactory = request.param
    clock = FrozenClock(START)
    with factory.build(clock, LIMITS) as adapter:
        yield adapter, clock


def new(order_id: str, expires_in: timedelta = timedelta(minutes=31)) -> NewOrder:
    return NewOrder(
        order_id=order_id,
        token_hash=f"hash-{order_id}",
        settings=SETTINGS,
        email="friend@example.test",
        checkout_expires_at=START + expires_in,
    )


def paid(store: OrderStore, order_id: str) -> None:
    store.create_awaiting_payment(new(order_id))
    store.mark_paid(order_id, {"session_id": f"cs_{order_id}"})


def queued(store: OrderStore, order_id: str) -> None:
    paid(store, order_id)
    store.set_manifest(order_id, files=[{"name": "a.mp4", "size": 10}], bytes_declared=10)
    store.queue(order_id)


def status(store: OrderStore, order_id: str) -> object:
    doc = store.get(order_id)
    assert doc is not None
    return doc["status"]


def test_unknown_order_is_none(orders: tuple[OrderStore, FrozenClock]) -> None:
    store, _ = orders
    assert store.get("0" * 32) is None


def test_create_holds_a_place_and_waits_for_payment(orders: tuple[OrderStore, FrozenClock]) -> None:
    store, _ = orders
    assert store.create_awaiting_payment(new("a" * 32)) == "a" * 32
    doc = store.get("a" * 32)
    assert doc is not None
    assert doc["status"] == "awaiting_payment"
    assert doc["place_held"] is True
    assert doc["week_id"] == "2026-W42"
    assert doc["token_hash"] == "hash-" + "a" * 32
    assert doc["created_at"] == START


def test_one_place_per_checkout_and_the_week_fills(orders: tuple[OrderStore, FrozenClock]) -> None:
    store, _ = orders
    store.create_awaiting_payment(new("a" * 32))
    store.create_awaiting_payment(new("b" * 32))
    with pytest.raises(WeekFull):
        store.create_awaiting_payment(new("c" * 32))
    assert store.get("c" * 32) is None


def test_expiry_releases_the_place(orders: tuple[OrderStore, FrozenClock]) -> None:
    store, _ = orders
    store.create_awaiting_payment(new("a" * 32))
    store.create_awaiting_payment(new("b" * 32))
    store.expire("a" * 32)
    assert status(store, "a" * 32) == "expired"
    store.create_awaiting_payment(new("c" * 32))  # the place came back
    assert status(store, "c" * 32) == "awaiting_payment"


def test_fulfilment_is_idempotent(orders: tuple[OrderStore, FrozenClock]) -> None:
    store, clock = orders
    paid(store, "a" * 32)
    first = store.get("a" * 32)
    clock.advance(timedelta(minutes=1))
    store.mark_paid("a" * 32, {"session_id": "cs_other"})
    store.expire("a" * 32)  # a late expiry does nothing once paid
    again = store.get("a" * 32)
    assert first is not None and again is not None
    assert again["status"] == "paid"
    assert again["paid_at"] == first["paid_at"] == START


def test_queue_needs_paid_and_take_slot_runs_two_at_a_time(
    orders: tuple[OrderStore, FrozenClock],
) -> None:
    store, _ = orders
    with pytest.raises(ValueError, match="not paid"):
        store.queue("0" * 32)
    for order_id in ("a" * 32, "b" * 32):
        queued(store, order_id)
    assert store.next_queued() == "a" * 32
    assert store.take_slot("a" * 32) is True
    assert store.take_slot("a" * 32) is False  # one run per order
    assert store.take_slot("b" * 32) is True
    doc = store.get("a" * 32)
    assert doc is not None
    assert doc["status"] == "running"
    assert doc["queue"]["lease_until"] == START + timedelta(minutes=70)  # type: ignore[index]
    assert doc["queue"]["run_token"]  # type: ignore[index]
    assert store.next_queued() is None


def test_no_third_slot(orders: tuple[OrderStore, FrozenClock]) -> None:
    store, clock = orders
    queued(store, "a" * 32)
    queued(store, "b" * 32)
    store.take_slot("a" * 32)
    store.take_slot("b" * 32)
    clock.advance(timedelta(days=7))  # next week: new places
    queued(store, "c" * 32)
    assert store.take_slot("c" * 32) is False
    assert status(store, "c" * 32) == "queued"
    store.release_slot("a" * 32)
    assert store.take_slot("c" * 32) is True


def test_stages_and_finish(orders: tuple[OrderStore, FrozenClock]) -> None:
    store, clock = orders
    queued(store, "a" * 32)
    store.take_slot("a" * 32)
    store.set_stage("a" * 32, name="reading")
    clock.advance(timedelta(minutes=2))
    store.set_stage("a" * 32, name="planning")
    doc = store.get("a" * 32)
    assert doc is not None
    assert doc["stage"] == {"name": "planning", "started_at": START + timedelta(minutes=2)}
    assert doc["stages_done"] == ["reading"]
    store.finish("a" * 32, result={"caption": "x"}, cost={"usd_total": "0.95"})
    doc = store.get("a" * 32)
    assert doc is not None
    assert doc["status"] == "done"
    assert doc["stages_done"] == ["reading", "planning"]
    queued(store, "b" * 32)
    assert store.take_slot("b" * 32) is True  # the slot was freed


def test_failure_gives_the_place_back(orders: tuple[OrderStore, FrozenClock]) -> None:
    store, _ = orders
    queued(store, "a" * 32)
    paid(store, "b" * 32)
    store.take_slot("a" * 32)
    store.fail("a" * 32, code=ErrorCode.RENDER_ERROR)
    doc = store.get("a" * 32)
    assert doc is not None
    assert doc["status"] == "failed"
    assert doc["error"] == {"code": "render_error"}
    store.create_awaiting_payment(new("c" * 32))  # D22: the week has a free place again


def test_pause_stops_launches_and_requeues_first(orders: tuple[OrderStore, FrozenClock]) -> None:
    store, clock = orders
    queued(store, "a" * 32)
    store.take_slot("a" * 32)
    clock.advance(timedelta(minutes=1))
    queued(store, "b" * 32)
    store.pause("a" * 32, code=ErrorCode.SPEND_LIMIT)
    assert status(store, "a" * 32) == "paused"
    assert store.take_slot("b" * 32) is False  # the service is paused (D26)


def test_viewed_feedback_and_delete(orders: tuple[OrderStore, FrozenClock]) -> None:
    store, clock = orders
    queued(store, "a" * 32)
    store.take_slot("a" * 32)
    store.finish("a" * 32, result={"caption": "x"}, cost={"usd_total": "0.95"})
    store.mark_viewed("a" * 32)
    clock.advance(timedelta(minutes=5))
    store.mark_viewed("a" * 32)  # set once
    store.set_feedback("a" * 32, rating=5, comment="great")
    doc = store.get("a" * 32)
    assert doc is not None
    assert doc["result_viewed_at"] == START
    assert doc["feedback"] == {"rating": 5, "comment": "great", "at": START + timedelta(minutes=5)}
    store.mark_deleted("a" * 32)
    assert status(store, "a" * 32) == "deleted"


def test_sweep_fails_dead_leases_expires_missed_checkouts_and_abandons(
    orders: tuple[OrderStore, FrozenClock],
) -> None:
    store, clock = orders
    queued(store, "a" * 32)
    store.take_slot("a" * 32)
    store.create_awaiting_payment(new("b" * 32, expires_in=timedelta(minutes=31)))
    clock.advance(timedelta(days=8))
    paid(store, "c" * 32)
    clock.advance(timedelta(days=8))
    report = store.sweep()
    assert status(store, "a" * 32) == "failed"
    doc_a = store.get("a" * 32)
    assert doc_a is not None and doc_a["error"] == {"code": "job_killed"}
    assert status(store, "b" * 32) == "expired"
    assert status(store, "c" * 32) == "abandoned"
    assert report == {"failed": ["a" * 32], "expired": ["b" * 32], "abandoned": ["c" * 32]}
    assert store.sweep() == {"failed": [], "expired": [], "abandoned": []}


def test_next_queued_is_first_come_not_first_by_id(orders: tuple[OrderStore, FrozenClock]) -> None:
    store, clock = orders
    queued(store, "b" * 32)
    clock.advance(timedelta(seconds=1))
    queued(store, "a" * 32)
    assert store.next_queued() == "b" * 32


def test_a_late_pause_still_pauses_the_service(orders: tuple[OrderStore, FrozenClock]) -> None:
    store, clock = orders
    queued(store, "a" * 32)
    store.take_slot("a" * 32)
    store.fail("a" * 32, code=ErrorCode.JOB_KILLED)  # the sweep got there first
    store.pause("a" * 32, code=ErrorCode.SPEND_LIMIT)  # the worker reports the spend limit late
    assert status(store, "a" * 32) == "failed"
    clock.advance(timedelta(seconds=1))
    queued(store, "b" * 32)
    assert store.take_slot("b" * 32) is False  # D26: the whole service is paused


def test_an_order_expires_after_the_retention_days(orders: tuple[OrderStore, FrozenClock]) -> None:
    store, _ = orders
    store.create_awaiting_payment(new("a" * 32))
    doc = store.get("a" * 32)
    assert doc is not None
    assert doc["expires_at"] == START + timedelta(days=LIMITS.order_days)  # Firestore TTL field


def test_each_email_is_claimed_once(orders: tuple[OrderStore, FrozenClock]) -> None:
    store, _ = orders
    paid(store, "a" * 32)
    assert store.claim_email("a" * 32, "failed") is True
    assert store.claim_email("a" * 32, "failed") is False
    assert store.claim_email("a" * 32, "ready") is True
    assert store.claim_email("0" * 32, "ready") is False
    doc = store.get("a" * 32)
    assert doc is not None
    emails = doc["emails"]
    assert isinstance(emails, dict) and set(emails) == {"failed_at", "ready_at"}


def test_queue_position_counts_the_orders_ahead(orders: tuple[OrderStore, FrozenClock]) -> None:
    store, clock = orders
    queued(store, "a" * 32)
    clock.advance(timedelta(seconds=1))
    queued(store, "b" * 32)
    assert store.queue_position("a" * 32) == 0
    assert store.queue_position("b" * 32) == 1
    store.take_slot("a" * 32)
    assert store.queue_position("a" * 32) is None  # running, not waiting
    assert store.queue_position("b" * 32) == 0
    assert store.queue_position("0" * 32) is None
