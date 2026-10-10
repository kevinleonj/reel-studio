"""STEP-07 task 5: the limits hold under concurrency (D55, F51), on the fake and on the Firestore
emulator (`make test-emulator`). Each case starts its callers together behind a barrier."""

import threading
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from reel_studio.adapters.storage_local import LocalStorage
from reel_studio.api import payments
from reel_studio.api.deps import ApiDeps
from reel_studio.api.tokens import hash_token
from reel_studio.core.config import load
from reel_studio.core.errors import WeekFull
from reel_studio.core.ports import NewOrder, OrderStore
from reel_studio.settings import WebSettings
from tests.conftest import MakeSettings
from tests.contract.orders_adapters import ADAPTERS, OrdersFactory
from tests.contract.test_orders import LIMITS, SETTINGS, START, queued
from tests.fakes.clock import FrozenClock
from tests.fakes.mailer import FakeMailer
from tests.fakes.payments import FakePayments

pytestmark = pytest.mark.race

CAP = 50
ALREADY = 45
CALLERS = 10
JOIN_TIMEOUT_S = 60.0


@pytest.fixture(params=[pytest.param(a, marks=a.marks, id=a.name) for a in ADAPTERS])
def orders(request: pytest.FixtureRequest) -> Iterator[tuple[OrderStore, FrozenClock]]:
    factory: OrdersFactory = request.param
    clock = FrozenClock(START)
    with factory.build(clock, replace(LIMITS, weekly_cap=CAP)) as adapter:
        yield adapter, clock


def together(count: int, call: Callable[[int], object]) -> list[object]:
    """Runs `call(i)` for every i at the same moment. WeekFull is returned as a result; any other
    error leaves None, which every assertion below rejects."""
    barrier = threading.Barrier(count)
    results: list[object] = [None] * count

    def run(i: int) -> None:
        barrier.wait()
        try:
            results[i] = call(i)
        except WeekFull as refused:  # the test counts the refusals
            results[i] = refused

    threads = [threading.Thread(target=run, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(JOIN_TIMEOUT_S)
        assert not thread.is_alive(), "a caller hung"
    return results


def order(i: int, token: str = "") -> NewOrder:
    return NewOrder(
        f"{i:032x}",
        hash_token(token) if token else f"hash-{i}",
        SETTINGS,
        "",
        START + timedelta(minutes=31),
    )


def test_ten_checkouts_for_the_last_five_places(orders: tuple[OrderStore, FrozenClock]) -> None:
    store, _ = orders
    for i in range(ALREADY):
        store.create_awaiting_payment(order(i))
    results = together(CALLERS, lambda i: store.create_awaiting_payment(order(ALREADY + i)))
    created = [r for r in results if isinstance(r, str)]
    refused = [r for r in results if isinstance(r, WeekFull)]
    assert (len(created), len(refused)) == (CAP - ALREADY, CALLERS - (CAP - ALREADY)), results
    assert len(store.list_orders(status="awaiting_payment", limit=CAP + CALLERS)) == CAP


def test_the_same_webhook_three_times_pays_once_and_emails_once(
    orders: tuple[OrderStore, FrozenClock], tmp_path: Path, make_settings: MakeSettings
) -> None:
    store, clock = orders
    settings = make_settings(
        WebSettings,
        payments="stripe",
        stripe_secret_key="test-stripe-key",
        stripe_webhook_secret="test-webhook-secret",
    )
    assert isinstance(settings, WebSettings)
    gateway, mailer = FakePayments(), FakeMailer()
    storage = LocalStorage(
        tmp_path, upload_path="/u", download_path="/d", signing_key=b"k" * 32, clock=clock
    )
    deps = ApiDeps(
        orders=store,
        storage=storage,
        local_storage=storage,
        mailer=mailer,
        payments=gateway,
        clock=clock,
        config=load(),
        settings=settings,
        voice_available=False,
        web_dist=None,
    )
    token, order_id = "the-link-token", f"{1:032x}"
    store.create_awaiting_payment(order(1, token))
    urls = {"success": f"{settings.site_url}/o/{order_id}?t={token}", "cancel": "unused"}
    session = gateway.create_checkout(order_id, "promo_x", urls, START + timedelta(minutes=31))
    session_id = str(session["session_id"])
    store.set_checkout(order_id, session_id=session_id)
    gateway.complete(session_id, "ana@example.test")

    results = together(3, lambda _: payments.fulfil(deps, session_id))

    assert results == [None, None, None]
    doc = store.get(order_id)
    assert doc is not None and doc["status"] == "paid"
    assert [(m.template, m.to) for m in mailer.sent] == [("link", "ana@example.test")]


def test_three_starts_for_two_slots(orders: tuple[OrderStore, FrozenClock]) -> None:
    store, clock = orders
    ids = []
    for i in range(3):
        clock.advance(timedelta(seconds=1))
        ids.append(f"{i:032x}")
        queued(store, ids[-1])
    results = together(3, lambda i: store.take_slot(ids[i]))
    assert sorted(results, key=str) == [False, True, True]
    running = store.list_orders(status="running", limit=len(ids))
    assert len(running) == LIMITS.running_max


def test_a_killed_worker_is_failed_by_the_sweep_and_its_slot_freed(
    orders: tuple[OrderStore, FrozenClock],
) -> None:
    store, clock = orders
    for i in range(3):
        queued(store, f"{i:032x}")
    assert store.take_slot(f"{0:032x}")
    assert store.take_slot(f"{1:032x}")
    assert not store.take_slot(f"{2:032x}")
    clock.advance(timedelta(minutes=LIMITS.lease_minutes + 1))  # the job died, no heartbeat
    report = store.sweep(expire_checkouts=True)
    assert sorted(report["failed"]) == [f"{0:032x}", f"{1:032x}"]
    assert store.take_slot(f"{2:032x}")


def test_three_claims_of_one_email_send_it_once(orders: tuple[OrderStore, FrozenClock]) -> None:
    """The claim itself must be atomic: a fulfil-level race reaches it staggered (review W3)."""
    store, _ = orders
    store.create_awaiting_payment(order(1))
    results = together(3, lambda _: store.claim_email(f"{1:032x}", "link"))
    assert sorted(results, key=str) == [False, False, True]
