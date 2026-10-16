"""The laptop's real editor (STEP-07 task 9): an order's uploads in, the engine's Reel out,
its cost on the order. The engine itself is replaced here; `make up` runs the real one."""

from decimal import Decimal
from pathlib import Path

from reel_studio.adapters.launcher_local import FakeEditor
from reel_studio.adapters.launcher_real import MadeReel, RealEditor
from reel_studio.core.errors import CostCapReached, ErrorCode, SpendLimitReached
from tests.fakes.clock import FrozenClock
from tests.fakes.orders import FakeOrders
from tests.fakes.storage import FakeStorage
from tests.unit.api.test_dispatcher import LIMITS, START, queued

ORDER, OTHER = f"{3:032x}", f"{4:032x}"


class Notices:
    """The dispatcher's failure notifier, recorded."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, ErrorCode, str]] = []

    def order_failed(self, order_id: str, code: ErrorCode, stage: str) -> None:
        self.sent.append((order_id, code, stage))

    def order_paused(self, order_id: str, stage: str) -> None:
        self.sent.append((order_id, ErrorCode.SPEND_LIMIT, stage))


def running(orders: FakeOrders, storage: FakeStorage, order_id: str = ORDER) -> None:
    queued(orders, order_id)
    assert orders.take_slot(order_id)
    target = storage.create_upload_session(order_id, {"name": "a.mp4", "size": 4})
    storage.complete(target, b"clip")


def test_the_real_editor_turns_the_uploads_into_a_finished_order(tmp_path: Path) -> None:
    clock = FrozenClock(START)
    orders, storage = FakeOrders(clock, LIMITS), FakeStorage()
    running(orders, storage)
    seen: dict[str, object] = {}

    def make_reel(inputs: Path, out: Path, settings: dict[str, object]) -> MadeReel:
        seen["inputs"] = sorted(p.name for p in inputs.iterdir())
        seen["bytes"] = (inputs / "a.mp4").read_bytes()
        seen["style"] = settings["style"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "text.mp4").write_bytes(b"with text")
        (out / "clean.mp4").write_bytes(b"clean")
        return MadeReel(
            text=out / "text.mp4",
            clean=out / "clean.mp4",
            cost_usd=Decimal("0.93"),
            duration_s=30,
            caption="Tomato toast",
            doubts=[],
            music_hint="warm lo-fi, mid tempo",
        )

    RealEditor(orders, storage, make_reel, notifier=Notices()).run(ORDER)
    assert seen == {"inputs": ["a.mp4"], "bytes": b"clip", "style": "recipe"}
    doc = orders.get(ORDER)
    assert doc is not None
    assert doc["status"] == "done"
    assert doc["cost"] == {"usd_total": "0.93"}
    result = doc["result"]
    assert isinstance(result, dict)
    assert [v["kind"] for v in result["versions"]] == ["text", "clean"]
    assert storage.objects[f"out/{ORDER}/text.mp4"] == b"with text"
    assert storage.objects[f"out/{ORDER}/clean.mp4"] == b"clean"
    assert result["caption"] == "Tomato toast"
    # The page reads `music.mood` and `music.tempo` (web/src/lib/types.ts); a null crashed it in
    # the STEP-07 e2e run. The engine has one hint, so it is the mood and the tempo stays empty.
    assert result["music"] == {"mood": "warm lo-fi, mid tempo", "tempo": ""}


def test_the_real_result_has_every_field_the_fake_one_has(tmp_path: Path) -> None:
    clock = FrozenClock(START)
    orders, storage = FakeOrders(clock, LIMITS), FakeStorage()
    running(orders, storage)
    FakeEditor(orders, storage, stage_seconds=0).run(ORDER)
    running(orders, storage, OTHER)

    def make_reel(inputs: Path, out: Path, settings: dict[str, object]) -> MadeReel:
        out.mkdir(parents=True, exist_ok=True)
        for name in ("text.mp4", "clean.mp4"):
            (out / name).write_bytes(b"x")
        return MadeReel(out / "text.mp4", out / "clean.mp4", Decimal(0), 30, "", [], None)

    RealEditor(orders, storage, make_reel, notifier=Notices()).run(OTHER)
    fake, real = orders.get(ORDER), orders.get(OTHER)
    assert fake is not None and real is not None
    assert isinstance(fake["result"], dict) and isinstance(real["result"], dict)
    for name, value in fake["result"].items():
        assert type(real["result"][name]) is type(value), name
    assert real["result"]["music"] == {"mood": "", "tempo": ""}


def test_an_editor_error_fails_the_order_with_its_own_code(tmp_path: Path) -> None:
    clock = FrozenClock(START)
    orders, storage = FakeOrders(clock, LIMITS), FakeStorage()
    running(orders, storage)

    def over_budget(inputs: Path, out: Path, settings: dict[str, object]) -> MadeReel:
        raise CostCapReached("the order's cap was reached")

    notices = Notices()
    RealEditor(orders, storage, over_budget, notifier=notices).run(ORDER)
    doc = orders.get(ORDER)
    assert doc is not None
    assert doc["status"] == "failed"
    assert doc["error"] == {"code": "cost_cap"}
    assert orders.capacity["slots"] == {}  # the slot is free for the next order
    assert notices.sent == [(ORDER, ErrorCode.COST_CAP, "planning")]  # EDITOR.md §10: Kevin knows


def test_the_monthly_spend_limit_pauses_the_order_and_the_service() -> None:
    # EDITOR.md §10: SpendLimitReached keeps the order (paused, place kept) and pauses the
    # service (D26), so the dispatcher stops launching into the wall.
    clock = FrozenClock(START)
    orders, storage = FakeOrders(clock, LIMITS), FakeStorage()
    running(orders, storage)

    def out_of_budget(inputs: Path, out: Path, settings: dict[str, object]) -> MadeReel:
        raise SpendLimitReached("the month's limit was reached")

    notices = Notices()
    RealEditor(orders, storage, out_of_budget, notifier=notices).run(ORDER)
    doc = orders.get(ORDER)
    assert doc is not None
    assert doc["status"] == "paused"
    assert orders.capacity["paused"] is True
    assert orders.capacity["slots"] == {}
    # Not a failure (the order starts again when the month resets), but Kevin and the customer
    # hear of it (D45).
    assert notices.sent == [(ORDER, ErrorCode.SPEND_LIMIT, "planning")]


def test_an_order_that_is_not_running_is_left_alone() -> None:
    clock = FrozenClock(START)
    orders, storage = FakeOrders(clock, LIMITS), FakeStorage()
    queued(orders, ORDER)
    called: list[str] = []

    def make_reel(inputs: Path, out: Path, settings: dict[str, object]) -> MadeReel:
        called.append("made")
        raise AssertionError("must not run")

    RealEditor(orders, storage, make_reel, notifier=Notices()).run(ORDER)
    assert called == []
