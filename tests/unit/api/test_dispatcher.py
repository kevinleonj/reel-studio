"""The laptop dispatcher (docs/ARCHITECTURE.md §2) and the fake editor (STEP-06 task 4)."""

from datetime import UTC, datetime, timedelta

from reel_studio.adapters.launcher_local import Dispatcher, FakeEditor
from reel_studio.core.ports import NewOrder, QueueLimits
from tests.fakes.clock import FrozenClock
from tests.fakes.orders import FakeOrders
from tests.fakes.storage import FakeStorage

START = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
LIMITS = QueueLimits(
    running_max=2,
    lease_minutes=70,
    weekly_cap=50,
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


class RecordingLauncher:
    def __init__(self) -> None:
        self.launched: list[str] = []

    def launch(self, order_id: str) -> str:
        self.launched.append(order_id)
        return f"run-{len(self.launched)}"


def queued(orders: FakeOrders, order_id: str) -> None:
    orders.create_awaiting_payment(
        NewOrder(order_id, f"h-{order_id}", SETTINGS, "", START + timedelta(minutes=31))
    )
    orders.mark_paid(order_id, {})
    orders.set_manifest(order_id, files=[{"name": "a.mp4", "size": 1}], bytes_declared=1)
    orders.queue(order_id)


def test_nothing_queued_launches_nothing() -> None:
    clock = FrozenClock(START)
    launcher = RecordingLauncher()
    Dispatcher(FakeOrders(clock, LIMITS), launcher, clock, sweep_every_s=60).tick()
    assert launcher.launched == []


def test_queued_orders_launch_up_to_the_slot_limit() -> None:
    clock = FrozenClock(START)
    orders = FakeOrders(clock, LIMITS)
    for order_id in ("a" * 32, "b" * 32, "c" * 32):
        clock.advance(timedelta(seconds=1))
        queued(orders, order_id)
    launcher = RecordingLauncher()
    Dispatcher(orders, launcher, clock, sweep_every_s=60).tick()
    assert launcher.launched == ["a" * 32, "b" * 32]
    assert orders.get("c" * 32)["status"] == "queued"  # type: ignore[index]


def test_sweep_runs_on_its_interval() -> None:
    clock = FrozenClock(START)
    orders = FakeOrders(clock, LIMITS)
    orders.create_awaiting_payment(
        NewOrder("a" * 32, "h", SETTINGS, "", START + timedelta(minutes=31))
    )
    dispatcher = Dispatcher(orders, RecordingLauncher(), clock, sweep_every_s=60)
    dispatcher.tick()  # first tick sweeps: nothing expired yet
    clock.advance(timedelta(minutes=40))
    dispatcher.tick()
    assert orders.get("a" * 32)["status"] == "expired"  # type: ignore[index]


def test_a_failing_launch_fails_the_order_and_frees_the_slot() -> None:
    class Broken:
        def launch(self, order_id: str) -> str:
            raise OSError("cannot start")

    clock = FrozenClock(START)
    orders = FakeOrders(clock, LIMITS)
    queued(orders, "a" * 32)
    Dispatcher(orders, Broken(), clock, sweep_every_s=60).tick()
    doc = orders.get("a" * 32)
    assert doc is not None and doc["status"] == "failed"
    assert orders.capacity["slots"] == {}


def test_fake_editor_walks_the_stages_and_writes_both_versions() -> None:
    clock = FrozenClock(START)
    orders = FakeOrders(clock, LIMITS)
    storage = FakeStorage()
    queued(orders, "a" * 32)
    orders.take_slot("a" * 32)
    stages: list[str] = []
    editor = FakeEditor(orders, storage, stage_seconds=0, on_stage=stages.append)
    editor.run("a" * 32)
    doc = orders.get("a" * 32)
    assert doc is not None
    assert stages == ["reading", "planning", "rendering", "checking", "saving"]
    assert doc["status"] == "done"
    assert doc["stages_done"] == stages
    result = doc["result"]
    assert isinstance(result, dict)
    assert {v["kind"] for v in result["versions"]} == {"text", "clean"}
    assert f"out/{'a' * 32}/text.mp4" in storage.objects
    assert f"out/{'a' * 32}/clean.mp4" in storage.objects


def test_fake_editor_listens_only_with_voice_on() -> None:
    clock = FrozenClock(START)
    orders = FakeOrders(clock, LIMITS)
    orders.create_awaiting_payment(
        NewOrder("a" * 32, "h", {**SETTINGS, "keep_voice": True}, "", START + timedelta(minutes=31))
    )
    orders.mark_paid("a" * 32, {})
    orders.set_manifest("a" * 32, files=[], bytes_declared=0)
    orders.queue("a" * 32)
    orders.take_slot("a" * 32)
    stages: list[str] = []
    FakeEditor(orders, FakeStorage(), stage_seconds=0, on_stage=stages.append).run("a" * 32)
    assert "listening" in stages
