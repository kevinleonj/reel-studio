"""Pins from the second phase B review (R2-W1 to R2-W7): each case fails when its fix is removed."""

import logging
import re
import smtplib
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reel_studio.adapters.mailer_smtp import SmtpMailer
from reel_studio.api import messages
from reel_studio.api.notify import Notifier
from reel_studio.api.ratelimit import SlidingWindow
from reel_studio.core.errors import DeliveryFailed, ErrorCode
from reel_studio.core.logging import JsonLineFormatter
from tests.fakes.clock import FrozenClock
from tests.fakes.mailer import FakeMailer
from tests.fakes.orders import FakeOrders
from tests.unit.api.conftest import LIMITS, Api
from tests.unit.api.test_notify import KEVIN, SITE, running

SETTINGS = {
    "style": "recipe",
    "length_s": 30,
    "text_lang": "en",
    "keep_voice": False,
    "chips": [],
    "note": "",
}
ORDER_URL = re.compile(r"^/o/(?P<id>[0-9a-f]{32})#t=(?P<token>.+)$")
START = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
MIB = 1024 * 1024
ADDRESS = "friend.of.the.reel@example.test"
LINK_DATA = {
    "order_id": "o",
    "order_url": "http://x/o/1",
    "max_files": 40,
    "max_total": "4 GB",
    "out_days": 30,
}


def new_order(api: Api) -> tuple[str, dict[str, str]]:
    body = api.client.post(
        "/api/checkout", json={"settings": SETTINGS, "code": "", "email": ""}
    ).json()
    match = ORDER_URL.match(body["order_url"])
    assert match is not None
    return match["id"], {"X-Order-Token": match["token"]}


def put_file(api: Api, order_id: str, auth: dict[str, str], name: str = "a.mp4") -> None:
    files = [{"name": name, "size": 4, "type": "video/mp4"}]
    [target] = api.client.post(
        f"/api/orders/{order_id}/uploads", json={"files": files}, headers=auth
    ).json()["targets"]
    response = api.client.put(
        target["upload_url"], content=b"0123", headers={"Content-Range": "bytes 0-3/4"}
    )
    assert response.status_code == 200


# ---------------------------------------------------------------- R2-W1 and the mail mapping


@pytest.mark.parametrize(
    "failure",
    [
        ConnectionRefusedError("down"),
        TimeoutError("slow"),
        smtplib.SMTPRecipientsRefused({ADDRESS: (550, b"5.1.1 user unknown")}),
        smtplib.SMTPServerDisconnected("bye"),
    ],
)
def test_every_smtp_failure_becomes_delivery_failed(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(smtplib, "SMTP", refuse)
    with pytest.raises(DeliveryFailed):
        SmtpMailer("127.0.0.1", 1, sender="r@example.test", timeout_s=1.0).send(
            "link", ADDRESS, LINK_DATA
        )


def test_a_refused_recipient_never_reaches_the_log(
    api: Api, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise smtplib.SMTPRecipientsRefused({ADDRESS: (550, b"5.1.1 user unknown")})

    monkeypatch.setattr(smtplib, "SMTP", refuse)
    mailer = SmtpMailer("127.0.0.1", 1, sender="r@example.test", timeout_s=1.0)
    app = cast(FastAPI, api.client.app)
    app.state.deps = replace(app.state.deps, mailer=mailer)  # the checkout now uses this mailer
    caplog.set_level(logging.DEBUG, logger="reel_studio")
    response = api.client.post(
        "/api/checkout", json={"settings": SETTINGS, "code": "", "email": ADDRESS}
    )
    assert response.status_code == 200
    clock = FrozenClock(START)
    orders = FakeOrders(clock, LIMITS)
    running(orders, "a" * 32, ADDRESS)
    orders.fail("a" * 32, code=ErrorCode.RENDER_ERROR)
    Notifier(orders, mailer, site_url=SITE, kevin=KEVIN).order_failed(
        "a" * 32, ErrorCode.RENDER_ERROR, "x"
    )
    lines = [JsonLineFormatter().format(record) for record in caplog.records]
    assert lines
    assert all(ADDRESS not in line for line in lines)


# ---------------------------------------------------------------- R2-W2 failure emails


def test_the_failure_messages_table_ships_with_the_code() -> None:
    assert messages.COPY_FILE.is_file()
    assert messages.failure_message("render_error")


def test_failure_emails_are_sent_once_each() -> None:
    clock = FrozenClock(START)
    orders, mailer = FakeOrders(clock, LIMITS), FakeMailer()
    running(orders, "a" * 32, "friend@example.test")
    orders.fail("a" * 32, code=ErrorCode.RENDER_ERROR)
    notifier = Notifier(orders, mailer, site_url=SITE, kevin=KEVIN)
    notifier.order_failed("a" * 32, ErrorCode.RENDER_ERROR, "rendering")
    notifier.order_failed("a" * 32, ErrorCode.RENDER_ERROR, "rendering")
    assert [m.template for m in mailer.sent] == ["kevin", "failed"]


def test_an_order_that_finished_after_all_gets_no_failure_email() -> None:
    clock = FrozenClock(START)
    orders, mailer = FakeOrders(clock, LIMITS), FakeMailer()
    running(orders, "a" * 32, "friend@example.test")
    orders.finish("a" * 32, result={}, cost={})
    Notifier(orders, mailer, site_url=SITE, kevin=KEVIN).order_failed(
        "a" * 32, ErrorCode.JOB_KILLED, "x"
    )
    assert mailer.sent == []


# ---------------------------------------------------------------- R2-W3 long paths


def test_a_very_long_path_segment_gets_the_404_page(api: Api) -> None:
    assert api.client.get("/" + "a" * 256).status_code == 404
    assert api.client.get("/" + "/".join(["abcd"] * 300)).status_code == 404


def test_a_very_long_session_id_is_an_unknown_session(api: Api) -> None:
    response = api.client.put(
        "/api/local-upload/" + "a" * 256, content=b"x", headers={"Content-Range": "bytes */1"}
    )
    assert response.status_code == 404


# ---------------------------------------------------------------- R2-W5, W6 guards and pins


def test_names_that_differ_only_in_case_are_the_same_file(api: Api) -> None:
    order_id, auth = new_order(api)
    files = [
        {"name": "Clip.MOV", "size": 1, "type": "video/quicktime"},
        {"name": "clip.mov", "size": 1, "type": "video/quicktime"},
    ]
    assert (
        api.client.post(
            f"/api/orders/{order_id}/uploads", json={"files": files}, headers=auth
        ).status_code
        == 422
    )


def test_a_delete_failure_leaves_the_status_alone(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    order_id, auth = new_order(api)
    put_file(api, order_id, auth)

    def broken(_: str) -> None:
        raise PermissionError("read-only")

    monkeypatch.setattr(api.storage, "delete_order", broken)
    client = TestClient(api.client.app, raise_server_exceptions=False)
    assert client.delete(f"/api/orders/{order_id}/files", headers=auth).status_code == 500
    assert api.orders.get(order_id)["status"] == "paid"  # type: ignore[index]


@pytest.mark.parametrize("move", ["running", "awaiting_payment"])
def test_delete_is_refused_while_files_may_be_read(api: Api, move: str) -> None:
    order_id, auth = new_order(api)
    put_file(api, order_id, auth)
    if move == "running":
        api.client.post(f"/api/orders/{order_id}/start", headers=auth)
        api.orders.take_slot(order_id)
    else:
        api.orders.orders[order_id]["status"] = "awaiting_payment"
    response = api.client.delete(f"/api/orders/{order_id}/files", headers=auth)
    assert (response.status_code, response.json()) == (409, {"error": "wrong_status"})


def test_a_chunk_of_exactly_the_limit_is_accepted(api: Api) -> None:
    order_id, auth = new_order(api)
    size, chunk = 16 * MIB, 8 * MIB
    files = [{"name": "big.mp4", "size": size, "type": "video/mp4"}]
    [target] = api.client.post(
        f"/api/orders/{order_id}/uploads", json={"files": files}, headers=auth
    ).json()["targets"]
    first = api.client.put(
        target["upload_url"],
        content=b"x" * chunk,
        headers={"Content-Range": f"bytes 0-{chunk - 1}/{size}"},
    )
    assert first.status_code == 308
    streamed = (b"y" * MIB for _ in range(8))
    second = api.client.put(
        target["upload_url"],
        content=streamed,
        headers={"Content-Range": f"bytes {chunk}-{size - 1}/{size}"},
    )
    assert second.status_code == 200


def test_the_batch_check_counts_files_already_uploaded(api: Api) -> None:
    order_id, auth = new_order(api)
    put_file(api, order_id, auth, "first.mp4")
    many = [{"name": f"n{i}.mp4", "size": 1, "type": "video/mp4"} for i in range(40)]
    response = api.client.post(
        f"/api/orders/{order_id}/uploads", json={"files": many}, headers=auth
    )
    assert (response.status_code, response.json()) == (413, {"error": "too_many_files"})


def test_the_batch_check_counts_bytes_already_uploaded(api: Api) -> None:
    order_id, auth = new_order(api)
    put_file(api, order_id, auth, "first.mp4")
    big = [{"name": "big.mp4", "size": 4_000_000_000 - 3, "type": "video/mp4"}]
    response = api.client.post(f"/api/orders/{order_id}/uploads", json={"files": big}, headers=auth)
    assert (response.status_code, response.json()) == (413, {"error": "too_large"})


def test_the_loser_of_a_concurrent_start_answers_200(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    order_id, auth = new_order(api)
    put_file(api, order_id, auth)
    real = api.orders.set_manifest
    first = {"done": False}

    def racing(oid: str, *, files: Sequence[Mapping[str, object]], bytes_declared: int) -> None:
        if not first["done"]:  # another Start wins between our status check and our write
            first["done"] = True
            real(oid, files=files, bytes_declared=bytes_declared)
            api.orders.queue(oid)
        real(oid, files=files, bytes_declared=bytes_declared)

    monkeypatch.setattr(api.orders, "set_manifest", racing)
    assert api.client.post(f"/api/orders/{order_id}/start", headers=auth).status_code == 200
    assert api.orders.get(order_id)["status"] == "queued"  # type: ignore[index]


def test_a_start_that_loses_to_a_delete_is_refused(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    order_id, auth = new_order(api)
    put_file(api, order_id, auth)
    real = api.orders.set_manifest

    def racing(oid: str, *, files: Sequence[Mapping[str, object]], bytes_declared: int) -> None:
        api.orders.mark_deleted(oid)
        real(oid, files=files, bytes_declared=bytes_declared)

    monkeypatch.setattr(api.orders, "set_manifest", racing)
    response = api.client.post(f"/api/orders/{order_id}/start", headers=auth)
    assert (response.status_code, response.json()) == (409, {"error": "wrong_status"})


# ---------------------------------------------------------------- R2-W7 rate limiter memory


def test_addresses_seen_once_are_forgotten() -> None:
    clock = FrozenClock(START)
    window = SlidingWindow(10, clock)
    for i in range(500):
        window.allow(f"10.0.{i // 250}.{i % 250}")
    clock.advance(timedelta(minutes=2))
    window.allow("10.9.9.9")
    assert len(window._calls) == 1
