"""REVIEW-FIXES WEB 1: upload limits count sessions not yet finished."""

import asyncio
from dataclasses import replace
from typing import cast

import pytest
from fastapi import FastAPI

from reel_studio.core.config import load
from reel_studio.core.errors import OrderBusy
from reel_studio.core.order_rules import WrongState
from tests.unit.api.conftest import Api
from tests.unit.api.test_api_orders import new_order

LIMITS = load().limits.order


def batch(path: str, api: Api, auth: dict[str, str], files: list[dict[str, object]]) -> object:
    response = api.client.post(path, json={"files": files}, headers=auth)
    return response.status_code, response.json()


def test_a_second_full_batch_is_refused_before_any_file_finishes(api: Api) -> None:
    """Declared sizes are reserved at /uploads; finished files alone are not the limit."""
    order_id, auth = new_order(api)
    path = f"/api/orders/{order_id}/uploads"
    size = LIMITS.max_total_bytes // 2
    first = [{"name": f"a{i}.mp4", "size": size, "type": "video/mp4"} for i in range(2)]
    assert batch(path, api, auth, first)[0] == 200  # type: ignore[index]
    second = [{"name": "b.mp4", "size": size, "type": "video/mp4"}]
    assert batch(path, api, auth, second) == (413, {"error": "too_large"})


def test_files_are_counted_across_batches_before_they_finish(api: Api) -> None:
    order_id, auth = new_order(api)
    path = f"/api/orders/{order_id}/uploads"
    first = [{"name": f"{i}.mp4", "size": 1, "type": "video/mp4"} for i in range(LIMITS.max_files)]
    assert batch(path, api, auth, first)[0] == 200  # type: ignore[index]
    one_more = [{"name": "extra.mp4", "size": 1, "type": "video/mp4"}]
    assert batch(path, api, auth, one_more) == (413, {"error": "too_many_files"})


def test_asking_again_for_the_same_file_does_not_count_it_twice(api: Api) -> None:
    """A replaced upload asks for its exact name again; a case variant is another stored file."""
    order_id, auth = new_order(api)
    path = f"/api/orders/{order_id}/uploads"
    size = LIMITS.max_total_bytes // 2
    clip = [{"name": "Clip.MP4", "size": size, "type": "video/mp4"}]
    for _ in range(3):
        assert batch(path, api, auth, clip)[0] == 200  # type: ignore[index]
    other = [{"name": "other.mp4", "size": size, "type": "video/mp4"}]
    assert batch(path, api, auth, other)[0] == 200  # type: ignore[index]
    variant = [{"name": "clip.mp4", "size": 1, "type": "video/mp4"}]
    assert batch(path, api, auth, variant) == (413, {"error": "too_large"})


def test_asking_again_smaller_does_not_free_room(api: Api) -> None:
    """Review round 1 CRITICAL: declare 4 GB, re-declare 0, and another 4 GB passed."""
    order_id, auth = new_order(api)
    path = f"/api/orders/{order_id}/uploads"
    full = LIMITS.max_total_bytes
    assert batch(path, api, auth, [file("a.mp4", full)])[0] == 200  # type: ignore[index]
    assert batch(path, api, auth, [file("a.mp4", 0)])[0] == 200  # type: ignore[index]
    assert batch(path, api, auth, [file("b.mp4", 1)]) == (413, {"error": "too_large"})


def test_asking_again_for_a_name_closes_its_older_session(api: Api) -> None:
    """One live session per stored name, so re-asking cannot open many uploads of one file."""
    order_id, auth = new_order(api)
    path = f"/api/orders/{order_id}/uploads"
    old = api.client.post(path, json={"files": [file("a.mp4", 4)]}, headers=auth).json()
    new = api.client.post(path, json={"files": [file("a.mp4", 4)]}, headers=auth).json()
    stale = api.client.put(
        old["targets"][0]["upload_url"], content=b"0123", headers={"Content-Range": "bytes 0-3/4"}
    )
    assert stale.status_code == 404
    fresh = api.client.put(
        new["targets"][0]["upload_url"], content=b"0123", headers={"Content-Range": "bytes 0-3/4"}
    )
    assert fresh.status_code == 200


def test_an_unsafe_name_reserves_nothing(api: Api) -> None:
    order_id, auth = new_order(api)
    path = f"/api/orders/{order_id}/uploads"
    unsafe = [file(".hidden.mp4", 1)]
    assert batch(path, api, auth, unsafe) == (422, {"error": "invalid_request"})
    many = [file(f"{i}.mp4", 1) for i in range(LIMITS.max_files)]
    assert batch(path, api, auth, many)[0] == 200  # type: ignore[index]


def file(name: str, size: int) -> dict[str, object]:
    return {"name": name, "size": size, "type": "video/mp4"}


class Racing:
    """An Orders stand-in whose reservation fails as the real adapter can."""

    def __init__(self, real: object, error: Exception) -> None:
        self._real = real
        self._error = error

    def __getattr__(self, name: str) -> object:
        return getattr(self._real, name)

    def reserve_uploads(self, *_: object, **__: object) -> None:
        raise self._error


def with_orders(api: Api, orders: object) -> None:
    app = cast(FastAPI, api.client.app)
    app.state.deps = replace(app.state.deps, orders=orders)


def test_a_start_that_won_the_race_answers_wrong_status(api: Api) -> None:
    order_id, auth = new_order(api)
    with_orders(api, Racing(api.orders, WrongState("started")))
    response = api.client.post(
        f"/api/orders/{order_id}/uploads", json={"files": [file("a.mp4", 1)]}, headers=auth
    )
    assert (response.status_code, response.json()) == (409, {"error": "wrong_status"})


def test_a_busy_order_record_answers_503_with_retry_after(api: Api) -> None:
    order_id, auth = new_order(api)
    with_orders(api, Racing(api.orders, OrderBusy("contention")))
    response = api.client.post(
        f"/api/orders/{order_id}/uploads", json={"files": [file("a.mp4", 1)]}, headers=auth
    )
    assert (response.status_code, response.json()) == (503, {"error": "busy"})
    assert response.headers["Retry-After"] == str(load().limits.web.busy_retry_after_s)


def test_a_second_upload_batch_while_one_runs_answers_busy_at_once(api: Api) -> None:
    """Review round 2: a 503 after 12 Firestore attempts still held a worker thread for
    seconds; a batch already in flight for this order now refuses the next one at once."""
    order_id, auth = new_order(api)
    in_flight = cast(FastAPI, api.client.app).state.limiters.order_writes
    assert in_flight.enter(order_id)
    response = api.client.post(
        f"/api/orders/{order_id}/uploads", json={"files": [file("a.mp4", 1)]}, headers=auth
    )
    assert (response.status_code, response.json()) == (503, {"error": "busy"})
    in_flight.leave(order_id)
    again = api.client.post(
        f"/api/orders/{order_id}/uploads", json={"files": [file("a.mp4", 1)]}, headers=auth
    )
    assert again.status_code == 200


@pytest.mark.parametrize(
    ("method", "action", "body"),
    [
        ("post", "feedback", {"rating": 5, "comment": ""}),
        ("post", "viewed", None),
        ("post", "start", None),
        ("delete", "files", None),
        ("post", "fulfil", None),
        ("post", "cancel", None),
    ],
)
def test_every_order_write_is_refused_at_once_while_another_runs(
    api: Api, method: str, action: str, body: dict[str, object] | None
) -> None:
    """Review round 3: a burst of feedback calls queued on the order record like uploads did."""
    order_id, auth = new_order(api)
    in_flight = cast(FastAPI, api.client.app).state.limiters.order_writes
    assert in_flight.enter(order_id)
    url = f"/api/orders/{order_id}/{action}"
    if method == "delete":
        response = api.client.delete(url, headers=auth)
    else:
        response = api.client.post(url, json=body, headers=auth)
    assert (response.status_code, response.json()) == (503, {"error": "busy"})


def test_the_write_slot_is_free_when_the_answer_is_sent(api: Api) -> None:
    """Review round 4: released after the response, a client's next write could get a stray
    503. TestClient waits for the whole app call, so the app is driven by hand here."""
    order_id, auth = new_order(api)
    app = cast(FastAPI, api.client.app)
    in_flight = app.state.limiters.order_writes
    seen: list[bool] = []
    statuses: list[int] = []
    path = f"/api/orders/{order_id}/viewed"
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"x"), (b"x-order-token", auth["X-Order-Token"].encode())],
        "client": ("127.0.0.1", 5000),
        "server": ("127.0.0.1", 80),
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        if message["type"] == "http.response.start":
            statuses.append(int(str(message["status"])))
        if message["type"] == "http.response.body" and not message.get("more_body", False):
            free = in_flight.enter(order_id)
            if free:
                in_flight.leave(order_id)
            seen.append(free)

    asyncio.run(app(scope, receive, send))  # type: ignore[arg-type]
    assert statuses == [200]  # the route ran: a 404 would never take the slot at all
    assert seen == [True]
