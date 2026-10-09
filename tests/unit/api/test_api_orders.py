"""The order routes (docs/ARCHITECTURE.md §7): status, uploads, files, start, viewed, feedback,
delete, fulfil, cancel, the laptop's chunk endpoint and signed downloads."""

import re
from datetime import timedelta
from urllib.parse import parse_qsl, urlsplit

import pytest

from reel_studio.core.errors import ErrorCode
from tests.unit.api.conftest import Api

SETTINGS = {
    "style": "recipe",
    "length_s": 30,
    "text_lang": "en",
    "keep_voice": False,
    "chips": [],
    "note": "",
}
ORDER_URL = re.compile(r"^/o/(?P<id>[0-9a-f]{32})#t=(?P<token>.+)$")
NOT_FOUND = {"error": "not_found"}


def new_order(api: Api) -> tuple[str, dict[str, str]]:
    body = api.client.post(
        "/api/checkout", json={"settings": SETTINGS, "code": "", "email": ""}
    ).json()
    match = ORDER_URL.match(body["order_url"])
    assert match is not None
    return match["id"], {"X-Order-Token": match["token"]}


def upload(
    api: Api, order_id: str, auth: dict[str, str], name: str = "a.mp4", data: bytes = b"0123"
) -> None:
    files = [{"name": name, "size": len(data), "type": "video/mp4"}]
    [target] = api.client.post(
        f"/api/orders/{order_id}/uploads", json={"files": files}, headers=auth
    ).json()["targets"]
    response = api.client.put(
        target["upload_url"],
        content=data,
        headers={"Content-Range": f"bytes 0-{len(data) - 1}/{len(data)}"},
    )
    assert response.status_code == 200


def test_status_view_of_a_new_paid_order(api: Api) -> None:
    order_id, auth = new_order(api)
    view = api.client.get(f"/api/orders/{order_id}", headers=auth).json()
    assert view == {
        "status": "paid",
        "settings": SETTINGS,
        "email_hint": None,
        "queue_position": None,
        "stage": None,
        "stages_done": [],
        "result": None,
        "error": None,
        "feedback_sent": False,
    }


@pytest.mark.parametrize("case", ["wrong token", "no token", "wrong id", "malformed id"])
def test_wrong_id_or_token_gets_the_same_404(api: Api, case: str) -> None:
    order_id, auth = new_order(api)
    path, headers = {
        "wrong token": (order_id, {"X-Order-Token": "nope"}),
        "no token": (order_id, {}),
        "wrong id": ("f" * 32, auth),
        "malformed id": ("../etc", auth),
    }[case]
    response = api.client.get(f"/api/orders/{path}", headers=headers)
    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_email_is_shown_masked(api: Api) -> None:
    body = api.client.post(
        "/api/checkout", json={"settings": SETTINGS, "code": "", "email": "kevin@gmail.com"}
    ).json()
    match = ORDER_URL.match(body["order_url"])
    assert match is not None
    view = api.client.get(
        f"/api/orders/{match['id']}", headers={"X-Order-Token": match["token"]}
    ).json()
    assert view["email_hint"] == "k•••@gmail.com"


def test_upload_batch_limits(api: Api) -> None:
    order_id, auth = new_order(api)
    path = f"/api/orders/{order_id}/uploads"
    too_many = [{"name": f"{i}.mp4", "size": 1, "type": "video/mp4"} for i in range(41)]
    assert api.client.post(path, json={"files": too_many}, headers=auth).json() == {
        "error": "too_many_files"
    }
    too_large = [{"name": "big.mp4", "size": 4_000_000_001, "type": "video/mp4"}]
    response = api.client.post(path, json={"files": too_large}, headers=auth)
    assert (response.status_code, response.json()) == (413, {"error": "too_large"})
    bad = [
        {"name": "a.mp4", "size": 1, "type": "video/mp4"},
        {"name": "song.mp3", "size": 1, "type": "audio/mpeg"},
    ]
    response = api.client.post(path, json={"files": bad}, headers=auth)
    assert (response.status_code, response.json()) == (
        415,
        {"error": "bad_type", "file": "song.mp3"},
    )
    assert api.client.post(path, json={"files": []}, headers=auth).json() == {"error": "no_files"}


def test_upload_and_list_files_and_the_chunk_protocol(api: Api) -> None:
    order_id, auth = new_order(api)
    files = [{"name": "a.mp4", "size": 6, "type": "video/mp4"}]
    [target] = api.client.post(
        f"/api/orders/{order_id}/uploads", json={"files": files}, headers=auth
    ).json()["targets"]
    url = target["upload_url"]
    first = api.client.put(url, content=b"012", headers={"Content-Range": "bytes 0-2/6"})
    assert (first.status_code, first.headers["Range"]) == (308, "bytes=0-2")
    query = api.client.put(url, headers={"Content-Range": "bytes */6"})
    assert (query.status_code, query.headers["Range"]) == (308, "bytes=0-2")
    assert (
        api.client.put(url, content=b"345", headers={"Content-Range": "bytes 3-5/6"}).status_code
        == 200
    )
    assert api.client.get(f"/api/orders/{order_id}/files", headers=auth).json() == {
        "files": [{"name": "a.mp4", "size": 6}]
    }
    assert (
        api.client.put(url, content=b"x", headers={"Content-Range": "nonsense"}).status_code == 400
    )
    assert (
        api.client.put(
            "/api/local-upload/unknown", content=b"x", headers={"Content-Range": "bytes */1"}
        ).status_code
        == 404
    )


def test_uploads_need_a_paid_order(api: Api) -> None:
    order_id, auth = new_order(api)
    upload(api, order_id, auth)
    api.client.post(f"/api/orders/{order_id}/start", headers=auth)
    files = [{"name": "b.mp4", "size": 1, "type": "video/mp4"}]
    response = api.client.post(
        f"/api/orders/{order_id}/uploads", json={"files": files}, headers=auth
    )
    assert (response.status_code, response.json()) == (409, {"error": "wrong_status"})


def test_start_needs_a_file_then_queues(api: Api) -> None:
    order_id, auth = new_order(api)
    response = api.client.post(f"/api/orders/{order_id}/start", headers=auth)
    assert (response.status_code, response.json()) == (409, {"error": "no_files"})
    upload(api, order_id, auth)
    assert api.client.post(f"/api/orders/{order_id}/start", headers=auth).status_code == 200
    view = api.client.get(f"/api/orders/{order_id}", headers=auth).json()
    assert (view["status"], view["queue_position"]) == ("queued", 0)
    doc = api.orders.get(order_id)
    assert doc is not None and doc["files"] == [{"name": "a.mp4", "size": 4}]


def finished(api: Api) -> tuple[str, dict[str, str]]:
    order_id, auth = new_order(api)
    upload(api, order_id, auth)
    api.client.post(f"/api/orders/{order_id}/start", headers=auth)
    api.orders.take_slot(order_id)
    api.orders.set_stage(order_id, name="reading")
    api.clock.advance(timedelta(minutes=3))
    return order_id, auth


def test_running_view_shows_the_stage_and_its_minutes(api: Api) -> None:
    order_id, auth = finished(api)
    view = api.client.get(f"/api/orders/{order_id}", headers=auth).json()
    assert view["status"] == "running"
    assert view["stage"] == {"name": "reading", "elapsed_s": 180}


def test_done_view_signs_both_versions_and_the_link_downloads(api: Api, tmp_path: object) -> None:
    order_id, auth = finished(api)
    source = api.storage._objects.parent / "reel.mp4"
    source.write_bytes(b"reel bytes")
    for kind in ("text", "clean"):
        api.storage.upload(source, f"out/{order_id}/{kind}.mp4", "video/mp4")
    versions = [{"kind": k, "key": f"out/{order_id}/{k}.mp4"} for k in ("text", "clean")]
    api.orders.finish(
        order_id, result={"versions": versions, "caption": "c", "duration_s": 30}, cost={}
    )
    view = api.client.get(f"/api/orders/{order_id}", headers=auth).json()
    [text, clean] = view["result"]["versions"]
    assert (text["kind"], clean["kind"]) == ("text", "clean")
    assert "key" not in text
    download = api.client.get(text["download_url"])
    assert download.status_code == 200 and download.content == b"reel bytes"
    assert download.headers["Content-Disposition"].startswith("attachment")
    parts = urlsplit(text["download_url"])
    query = dict(parse_qsl(parts.query))
    tampered = f"{parts.path}?exp={query['exp']}&name={query['name']}&sig={'0' * 64}"
    assert api.client.get(tampered).status_code == 404
    api.clock.advance(timedelta(minutes=61))
    assert api.client.get(text["download_url"]).status_code == 404  # expired


def test_viewed_feedback_and_delete(api: Api) -> None:
    order_id, auth = finished(api)
    api.orders.finish(order_id, result={"versions": [], "caption": "c", "duration_s": 30}, cost={})
    assert api.client.post(f"/api/orders/{order_id}/viewed", headers=auth).status_code == 200
    bad = api.client.post(
        f"/api/orders/{order_id}/feedback", json={"rating": 6, "comment": ""}, headers=auth
    )
    assert bad.status_code == 422
    long = api.client.post(
        f"/api/orders/{order_id}/feedback", json={"rating": 5, "comment": "x" * 1001}, headers=auth
    )
    assert long.status_code == 422
    ok = api.client.post(
        f"/api/orders/{order_id}/feedback", json={"rating": 5, "comment": "great"}, headers=auth
    )
    assert ok.status_code == 200
    assert api.client.get(f"/api/orders/{order_id}", headers=auth).json()["feedback_sent"] is True
    assert api.client.delete(f"/api/orders/{order_id}/files", headers=auth).status_code == 200
    assert api.client.get(f"/api/orders/{order_id}", headers=auth).json()["status"] == "deleted"
    assert api.storage.list_inputs(order_id) == []


def test_failed_view_carries_only_the_code(api: Api) -> None:
    order_id, auth = finished(api)
    api.orders.fail(order_id, code=ErrorCode.RENDER_ERROR)
    view = api.client.get(f"/api/orders/{order_id}", headers=auth).json()
    assert (view["status"], view["error"]) == ("failed", {"code": "render_error"})


def test_fulfil_and_cancel_are_harmless_when_payments_are_off(api: Api) -> None:
    order_id, auth = new_order(api)
    assert api.client.post(f"/api/orders/{order_id}/fulfil", headers=auth).status_code == 200
    cancelled = api.client.post(f"/api/orders/{order_id}/cancel", headers=auth)
    assert cancelled.status_code == 200
    assert cancelled.json() == {"settings": SETTINGS}
    assert api.client.get(f"/api/orders/{order_id}", headers=auth).json()["status"] == "paid"


def test_order_calls_are_rate_limited(api: Api) -> None:
    order_id, auth = new_order(api)
    codes = {
        api.client.get(f"/api/orders/{order_id}", headers=auth).status_code for _ in range(121)
    }
    assert codes == {200, 429}


def test_the_internal_sweep_refuses_callers_without_an_identity(api: Api) -> None:
    response = api.client.post("/api/internal/sweep")
    assert (response.status_code, response.json()) == (401, {"error": "unauthorized"})
