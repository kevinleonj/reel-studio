"""Failure emails (UX §3, EDITOR §10 "every failure emails Kevin"), sent once each (§4), and a
dispatcher that survives its own errors (senior review W2, W7)."""

import threading
from datetime import UTC, datetime, timedelta

from reel_studio.adapters.launcher_local import Dispatcher
from reel_studio.api.notify import Notifier
from reel_studio.core import order_rules
from reel_studio.core.config import load
from reel_studio.core.errors import DeliveryFailed, ErrorCode
from reel_studio.core.ports import NewOrder
from tests.fakes.clock import FrozenClock
from tests.fakes.mailer import FakeMailer
from tests.fakes.orders import FakeOrders
from tests.unit.api.test_dispatcher import LIMITS, SETTINGS, RecordingLauncher

START = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
KEVIN = "kevin@example.test"
SITE = "http://127.0.0.1:8080"


def running(orders: FakeOrders, order_id: str, email: str) -> None:
    orders.create_awaiting_payment(
        NewOrder(order_id, "h", SETTINGS, email, START + timedelta(minutes=31))
    )
    orders.mark_paid(order_id, {})
    orders.set_manifest(order_id, files=[], bytes_declared=0)
    orders.queue(order_id)
    orders.take_slot(order_id)


def notifier(orders: FakeOrders, mailer: FakeMailer) -> Notifier:
    return Notifier(orders, mailer, site_url=SITE, kevin=KEVIN)


def test_a_dead_lease_emails_the_customer_and_kevin_once() -> None:
    clock = FrozenClock(START)
    orders, mailer = FakeOrders(clock, LIMITS), FakeMailer()
    running(orders, "a" * 32, "friend@example.test")
    dispatcher = Dispatcher(
        orders, RecordingLauncher(), clock, sweep_every_s=60, notifier=notifier(orders, mailer)
    )
    clock.advance(timedelta(minutes=71))
    dispatcher.tick()
    clock.advance(timedelta(minutes=2))
    dispatcher.tick()  # a second sweep finds nothing new and sends nothing
    assert [(m.template, m.to) for m in mailer.sent] == [
        ("kevin", KEVIN),
        ("failed", "friend@example.test"),
    ]
    failed = mailer.sent[1]
    assert "Something broke while cutting. Kevin has been notified." in failed.text
    assert f"{SITE}/new" in failed.text
    assert mailer.sent[0].subject == f"[reel-studio] failed {'a' * 32} at running: job_killed"


def test_without_an_email_only_kevin_hears() -> None:
    clock = FrozenClock(START)
    orders, mailer = FakeOrders(clock, LIMITS), FakeMailer()
    running(orders, "a" * 32, "")
    orders.fail("a" * 32, code=ErrorCode.RENDER_ERROR)
    notifier(orders, mailer).order_failed("a" * 32, ErrorCode.RENDER_ERROR, "rendering")
    assert [m.to for m in mailer.sent] == [KEVIN]


def test_a_mail_server_failure_never_breaks_the_caller() -> None:
    class DownMailer(FakeMailer):
        def send(self, template: str, to: str, data: object) -> None:
            raise DeliveryFailed("smtp down")

    clock = FrozenClock(START)
    orders = FakeOrders(clock, LIMITS)
    running(orders, "a" * 32, "friend@example.test")
    orders.fail("a" * 32, code=ErrorCode.RENDER_ERROR)  # the notifier speaks only for failed orders
    Notifier(orders, DownMailer(), site_url=SITE, kevin=KEVIN).order_failed(
        "a" * 32, ErrorCode.RENDER_ERROR, "x"
    )


def test_any_launch_error_fails_the_order_frees_the_slot_and_tells_kevin() -> None:
    class Crashing:
        def launch(self, order_id: str) -> str:
            raise RuntimeError("bad image")

    clock = FrozenClock(START)
    orders, mailer = FakeOrders(clock, LIMITS), FakeMailer()
    orders.create_awaiting_payment(
        NewOrder("a" * 32, "h", SETTINGS, "", START + timedelta(minutes=31))
    )
    orders.mark_paid("a" * 32, {})
    orders.set_manifest("a" * 32, files=[], bytes_declared=0)
    orders.queue("a" * 32)
    Dispatcher(
        orders, Crashing(), clock, sweep_every_s=60, notifier=notifier(orders, mailer)
    ).tick()
    doc = orders.get("a" * 32)
    assert doc is not None and doc["status"] == "failed"
    assert orders.capacity["slots"] == {}
    assert [m.template for m in mailer.sent] == ["kevin"]


def test_the_dispatcher_survives_an_error_in_one_tick() -> None:
    clock = FrozenClock(START)
    orders = FakeOrders(clock, LIMITS)
    stop = threading.Event()
    calls = {"n": 0}
    real = orders.next_queued

    def flaky() -> str | None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("emulator not ready")
        stop.set()
        return real()

    orders.next_queued = flaky  # type: ignore[method-assign]
    Dispatcher(orders, RecordingLauncher(), clock, sweep_every_s=60).run_forever(0, stop)
    assert calls["n"] == 2


def test_queue_limits_come_from_the_config() -> None:
    limits = order_rules.limits_from(load())
    assert (limits.running_max, limits.lease_minutes, limits.weekly_cap) == (2, 70, 50)
    assert (limits.paid_not_started_days, limits.expiry_grace_minutes, limits.order_days) == (
        7,
        5,
        30,
    )
