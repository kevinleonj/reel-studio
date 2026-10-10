"""Pins from the third phase B review (R3-W1 to R3-W3): each fails when its fix is removed."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import reel_studio.api.notify as notify_module
from reel_studio.adapters.launcher_local import Dispatcher
from reel_studio.adapters.storage_local import ChunkAnswer, LocalStorage
from reel_studio.api.notify import Notifier
from reel_studio.api.ratelimit import SlidingWindow
from reel_studio.core.errors import DeliveryFailed, ErrorCode
from tests.fakes.clock import FrozenClock
from tests.fakes.mailer import FakeMailer
from tests.fakes.orders import FakeOrders
from tests.unit.api.conftest import Api
from tests.unit.api.test_api_pins import new_order
from tests.unit.api.test_dispatcher import LIMITS, RecordingLauncher
from tests.unit.api.test_notify import KEVIN, SITE, running

START = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
ORDER = "a" * 32


def storage_in(tmp_path: Path) -> LocalStorage:
    return LocalStorage(
        tmp_path / "data",
        upload_path="/api/local-upload",
        download_path="/api/local-files",
        signing_key=b"k" * 32,
        clock=FrozenClock(START),
    )


def session_of(storage: LocalStorage, size: int, name: str = "a.mp4") -> str:
    target = storage.create_upload_session(ORDER, {"name": name, "size": size, "type": "video/mp4"})
    return str(target["upload_url"]).rsplit("/", 1)[1]


def missing(code: str) -> str:
    raise FileNotFoundError("en.json")


# ---------------------------------------------------------------- R3-W1 Kevin first


@pytest.mark.parametrize("email", ["", "friend@example.test"])
def test_kevin_is_told_even_when_the_words_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch, email: str
) -> None:
    orders, mailer = FakeOrders(FrozenClock(START), LIMITS), FakeMailer()
    running(orders, ORDER, email)
    orders.fail(ORDER, code=ErrorCode.RENDER_ERROR)
    monkeypatch.setattr(notify_module, "failure_message", missing)
    Notifier(orders, mailer, site_url=SITE, kevin=KEVIN).order_failed(
        ORDER, ErrorCode.RENDER_ERROR, "x"
    )
    assert [m.template for m in mailer.sent] == ["kevin"]
    assert orders.claim_email(ORDER, "failed") is True  # the customer email was never claimed


# ---------------------------------------------------------------- R3-W2 tests that reach the mailer


def test_a_down_mail_server_never_stops_the_caller_and_both_sends_are_tried() -> None:
    attempts: list[str] = []

    class DownMailer(FakeMailer):
        def send(self, template: str, to: str, data: object) -> None:
            attempts.append(template)
            raise DeliveryFailed("smtp down")

    orders = FakeOrders(FrozenClock(START), LIMITS)
    running(orders, ORDER, "friend@example.test")
    orders.fail(ORDER, code=ErrorCode.RENDER_ERROR)
    Notifier(orders, DownMailer(), site_url=SITE, kevin=KEVIN).order_failed(
        ORDER, ErrorCode.RENDER_ERROR, "x"
    )
    assert attempts == ["kevin", "failed"]


# ---------------------------------------------------------------- R3-W3 pins for each fix


def test_one_failed_notice_does_not_skip_the_next_order() -> None:
    clock = FrozenClock(START)
    orders = FakeOrders(clock, LIMITS)
    running(orders, "a" * 32, "x@example.test")
    running(orders, "b" * 32, "y@example.test")

    class Flaky:
        def __init__(self) -> None:
            self.seen: list[str] = []

        def order_failed(self, order_id: str, code: ErrorCode, stage: str) -> None:
            self.seen.append(order_id)
            if len(self.seen) == 1:
                raise FileNotFoundError("table missing")

    flaky = Flaky()
    clock.advance(timedelta(minutes=71))
    Dispatcher(orders, RecordingLauncher(), clock, sweep_every_s=60, notifier=flaky).tick()
    assert flaky.seen == ["a" * 32, "b" * 32]


def test_composed_and_decomposed_names_are_one_file(api: Api) -> None:
    order_id, auth = new_order(api)
    composed, decomposed = "caf\u00e9.mov", "cafe\u0301.mov"  # one code point, or e + accent
    assert composed != decomposed
    files = [
        {"name": composed, "size": 1, "type": "video/quicktime"},
        {"name": decomposed, "size": 1, "type": "video/quicktime"},
    ]
    response = api.client.post(
        f"/api/orders/{order_id}/uploads", json={"files": files}, headers=auth
    )
    assert response.status_code == 422


def test_a_prune_keeps_the_calls_still_inside_the_window() -> None:
    clock = FrozenClock(START)
    window = SlidingWindow(3, clock)
    assert window.allow("a")
    clock.advance(timedelta(seconds=20))
    assert window.allow("a")
    clock.advance(timedelta(seconds=20))
    assert window.allow("a")
    clock.advance(timedelta(seconds=21))  # t=61: the first call is out, two are still in
    assert window.allow("a")
    assert not window.allow("a")


def test_a_session_whose_bytes_are_nowhere_is_not_complete(tmp_path: Path) -> None:
    storage = storage_in(tmp_path)
    session = session_of(storage, 4)
    storage.put_chunk(session, "bytes 0-3/4", b"0123")
    record = json.loads(storage._session_file(session).read_text())
    record.pop("complete")
    storage._write_record(session, record)
    (tmp_path / "data" / "objects" / "in" / ORDER / "a.mp4").unlink()
    with pytest.raises(ValueError):
        storage.put_chunk(session, "bytes */4", b"")


def test_a_status_query_reports_a_short_partial_truthfully(tmp_path: Path) -> None:
    storage = storage_in(tmp_path)
    session = session_of(storage, 8)
    storage.put_chunk(session, "bytes 0-3/8", b"0123")
    storage.partial_of(session).write_bytes(b"01")
    assert storage.put_chunk(session, "bytes */8", b"") == ChunkAnswer(308, "bytes=0-1")


def test_a_status_query_heals_a_record_that_outran_its_bytes(tmp_path: Path) -> None:
    storage = storage_in(tmp_path)
    session = session_of(storage, 8)
    storage.put_chunk(session, "bytes 0-3/8", b"0123")
    record = json.loads(storage._session_file(session).read_text())
    storage._write_record(session, {**record, "received": 8})  # the record says done, the disk not
    storage.partial_of(session).write_bytes(b"012345")
    assert storage.put_chunk(session, "bytes */8", b"") == ChunkAnswer(308, "bytes=0-5")


def test_download_refuses_a_key_outside_the_store(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        storage_in(tmp_path).download("../outside", tmp_path / "x")


def test_start_rechecks_the_bytes_that_actually_arrived(api: Api) -> None:
    order_id, auth = new_order(api)
    folder = api.storage._path(f"in/{order_id}")
    folder.mkdir(parents=True)
    with (folder / "big.mp4").open("wb") as handle:
        handle.truncate(4_000_000_001)  # sparse: no disk used
    response = api.client.post(f"/api/orders/{order_id}/start", headers=auth)
    assert (response.status_code, response.json()) == (413, {"error": "too_large"})


def test_an_older_completed_session_replayed_after_a_newer_upload_answers_200(
    tmp_path: Path,
) -> None:
    storage = storage_in(tmp_path)
    first = session_of(storage, 4)
    storage.put_chunk(first, "bytes 0-3/4", b"0123")
    second = session_of(storage, 6)  # the file was edited and chosen again: same name, new size
    storage.put_chunk(second, "bytes 0-5/6", b"abcdef")
    assert storage.put_chunk(first, "bytes */4", b"") == ChunkAnswer(200, None)
    assert (tmp_path / "data" / "objects" / "in" / ORDER / "a.mp4").read_bytes() == b"abcdef"
    assert not storage.partial_of(first).exists()


def test_a_file_name_longer_than_the_disk_allows_is_refused(api: Api) -> None:
    order_id, auth = new_order(api)
    files = [{"name": "a" * 300 + ".mp4", "size": 1, "type": "video/mp4"}]
    response = api.client.post(
        f"/api/orders/{order_id}/uploads", json={"files": files}, headers=auth
    )
    assert response.status_code == 422
