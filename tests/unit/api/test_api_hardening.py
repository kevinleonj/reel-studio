"""Cases from the phase B senior review (W1, W3-W6, W8, W10, S3, S5): each pins a fix."""

import asyncio
import logging
import re
from collections.abc import Iterator, MutableMapping
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import pytest

from reel_studio.core.errors import DeliveryFailed
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
FILE = {"name": "a.mp4", "size": 4, "type": "video/mp4"}


def new_order(api: Api, email: str = "") -> tuple[str, dict[str, str]]:
    response = api.client.post(
        "/api/checkout", json={"settings": SETTINGS, "code": "", "email": email}
    )
    match = ORDER_URL.match(response.json()["order_url"])
    assert match is not None
    return match["id"], {"X-Order-Token": match["token"]}


def put_file(api: Api, order_id: str, auth: dict[str, str], name: str = "a.mp4") -> None:
    files = [{**FILE, "name": name}]
    [target] = api.client.post(
        f"/api/orders/{order_id}/uploads", json={"files": files}, headers=auth
    ).json()["targets"]
    assert (
        api.client.put(
            target["upload_url"], content=b"0123", headers={"Content-Range": "bytes 0-3/4"}
        ).status_code
        == 200
    )


# ---------------------------------------------------------------- W1: email after the order exists


def test_a_mail_server_failure_still_returns_the_order_link(api: Api) -> None:
    def down(template: str, to: str, data: object) -> None:
        raise DeliveryFailed(template)

    api.mailer.send = down  # type: ignore[method-assign]
    response = api.client.post(
        "/api/checkout", json={"settings": SETTINGS, "code": "", "email": "friend@example.test"}
    )
    assert response.status_code == 200
    assert ORDER_URL.match(response.json()["order_url"])


@pytest.mark.parametrize(
    "email", ["no-at-sign", "a@b", "friend@example.test\r\nBcc: x@y.z", "a b@c.de"]
)
def test_a_malformed_email_is_refused_before_any_order(api: Api, email: str) -> None:
    response = api.client.post(
        "/api/checkout", json={"settings": SETTINGS, "code": "", "email": email}
    )
    assert response.status_code == 422
    assert api.orders.orders == {}


# ---------------------------------------------------------------- W3: no unauthenticated 500s


@pytest.mark.parametrize(
    "settings",
    [
        {**SETTINGS, "style": ["recipe"]},
        {**SETTINGS, "text_lang": {"en": 1}},
        {**SETTINGS, "length_s": "30"},
    ],
)
def test_wrongly_typed_settings_are_refused(api: Api, settings: dict[str, object]) -> None:
    response = api.client.post(
        "/api/checkout", json={"settings": settings, "code": "", "email": ""}
    )
    assert response.status_code == 422


@pytest.mark.parametrize("path", ["/%00", "/_astro/%00", "/privacy%00"])
def test_nul_bytes_in_paths_get_the_404_page(api: Api, path: str) -> None:
    assert api.client.get(path).status_code == 404


# ---------------------------------------------------------------- W4-W6: order guards


def test_start_twice_is_harmless(api: Api) -> None:
    order_id, auth = new_order(api)
    put_file(api, order_id, auth)
    assert api.client.post(f"/api/orders/{order_id}/start", headers=auth).status_code == 200
    assert api.client.post(f"/api/orders/{order_id}/start", headers=auth).status_code == 200
    assert api.orders.get(order_id)["status"] == "queued"  # type: ignore[index]


def test_start_rechecks_the_limits_against_what_was_uploaded(api: Api) -> None:
    order_id, auth = new_order(api)
    targets = []
    for batch in ("a", "b"):  # two batches of 40 before any upload finishes: 80 sessions
        many = [{**FILE, "name": f"{batch}{i}.mp4"} for i in range(40)]
        targets += api.client.post(
            f"/api/orders/{order_id}/uploads", json={"files": many}, headers=auth
        ).json()["targets"]
    for i, target in enumerate(targets):
        api.storage.put_chunk(target["upload_url"].rsplit("/", 1)[1], "bytes 0-3/4", b"0123")
        if i == 40:
            break
    response = api.client.post(f"/api/orders/{order_id}/start", headers=auth)
    assert (response.status_code, response.json()) == (413, {"error": "too_many_files"})


def test_a_batch_with_the_same_name_twice_is_refused(api: Api) -> None:
    order_id, auth = new_order(api)
    response = api.client.post(
        f"/api/orders/{order_id}/uploads", json={"files": [FILE, FILE]}, headers=auth
    )
    assert response.status_code == 422


def test_feedback_needs_a_finished_order(api: Api) -> None:
    order_id, auth = new_order(api)
    response = api.client.post(
        f"/api/orders/{order_id}/feedback", json={"rating": 5, "comment": ""}, headers=auth
    )
    assert (response.status_code, response.json()) == (409, {"error": "wrong_status"})


def test_delete_is_refused_while_the_editor_may_read_the_files(api: Api) -> None:
    order_id, auth = new_order(api)
    put_file(api, order_id, auth)
    api.client.post(f"/api/orders/{order_id}/start", headers=auth)
    response = api.client.delete(f"/api/orders/{order_id}/files", headers=auth)
    assert (response.status_code, response.json()) == (409, {"error": "wrong_status"})


def test_a_failed_delete_can_be_retried_and_never_claims_success(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    order_id, auth = new_order(api)
    put_file(api, order_id, auth)
    real = api.storage.delete_order

    def broken(oid: str) -> None:
        raise PermissionError("folder is read-only")

    monkeypatch.setattr(api.storage, "delete_order", broken)
    client = api.client.__class__(api.client.app, raise_server_exceptions=False)
    assert client.delete(f"/api/orders/{order_id}/files", headers=auth).status_code == 500
    assert (
        api.storage.list_inputs(order_id) != []
    )  # the files are still there, and nobody said otherwise
    monkeypatch.setattr(api.storage, "delete_order", real)
    assert api.client.delete(f"/api/orders/{order_id}/files", headers=auth).status_code == 200
    assert api.storage.list_inputs(order_id) == []


# ---------------------------------------------------------------- W8: tests for likely breaks

ORDER_ROUTES = [
    ("GET", ""),
    ("POST", "/fulfil"),
    ("POST", "/cancel"),
    ("POST", "/uploads"),
    ("GET", "/files"),
    ("POST", "/start"),
    ("POST", "/viewed"),
    ("POST", "/feedback"),
    ("DELETE", "/files"),
]


@pytest.mark.parametrize(("method", "suffix"), ORDER_ROUTES)
def test_every_order_route_answers_a_wrong_token_with_the_same_404(
    api: Api, method: str, suffix: str
) -> None:
    order_id, _ = new_order(api)
    response = api.client.request(
        method, f"/api/orders/{order_id}{suffix}", headers={"X-Order-Token": "nope"}, json={}
    )
    assert (response.status_code, response.json()) == (404, {"error": "not_found"})


@pytest.fixture
def signed(api: Api) -> Iterator[tuple[Api, str]]:
    order_id, _ = new_order(api)
    source = api.storage._objects.parent / "reel.mp4"
    source.write_bytes(b"reel")
    api.storage.upload(source, f"out/{order_id}/text.mp4", "video/mp4")
    api.storage.upload(source, f"out/{order_id}/clean.mp4", "video/mp4")
    yield api, api.storage.signed_url(f"out/{order_id}/text.mp4", "reel.mp4", 60)


@pytest.mark.parametrize("field", ["exp", "name", "key"])
def test_changing_any_signed_field_breaks_the_link(signed: tuple[Api, str], field: str) -> None:
    api, url = signed
    assert api.client.get(url).status_code == 200
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    path = parts.path
    if field == "key":
        path = path.replace("text.mp4", "clean.mp4")
    else:
        query[field] = str(int(query[field]) + 3600) if field == "exp" else "other.mp4"
    tampered = f"{path}?exp={query['exp']}&name={query['name']}&sig={query['sig']}"
    assert api.client.get(tampered).status_code == 404


def test_a_link_signed_with_another_key_is_refused(signed: tuple[Api, str]) -> None:
    api, url = signed
    api.storage._key = b"x" * 32
    assert api.client.get(url).status_code == 404


def test_non_ascii_signatures_are_refused_not_crashed(signed: tuple[Api, str]) -> None:
    api, url = signed
    assert api.client.get(url.split("&sig=")[0] + "&sig=%C3%A9").status_code == 404


def test_request_logs_carry_no_path_or_query_values(
    signed: tuple[Api, str], caplog: pytest.LogCaptureFixture
) -> None:
    api, url = signed
    caplog.set_level(logging.INFO, logger="reel_studio")
    api.client.get(url)
    sig = dict(parse_qsl(urlsplit(url).query))["sig"]
    for record in caplog.records:
        assert sig not in str(record.__dict__)
        assert "exp=" not in record.getMessage()


def test_a_raw_dot_dot_path_never_leaves_the_site_folder(api: Api, tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_text("secret")

    async def raw_get(path: str) -> int:
        sent: list[MutableMapping[str, Any]] = []
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
            "path": path, "raw_path": path.encode(), "query_string": b"", "headers": [],
            "client": ("127.0.0.1", 1), "server": ("test", 80), "scheme": "http", "root_path": "",
        }  # fmt: skip

        async def receive() -> dict[str, object]:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: MutableMapping[str, Any]) -> None:
            sent.append(message)

        await api.client.app(scope, receive, send)
        return int(str(sent[0]["status"]))

    assert asyncio.run(raw_get("/../secret.txt")) == 404
    assert asyncio.run(raw_get("/_astro/../../secret.txt")) == 404


# ---------------------------------------------------------------- W10, S3, S5


def test_a_chunked_body_over_the_chunk_limit_is_refused(api: Api) -> None:
    order_id, auth = new_order(api)
    files = [{**FILE, "size": 9 * 1024 * 1024}]
    [target] = api.client.post(
        f"/api/orders/{order_id}/uploads", json={"files": files}, headers=auth
    ).json()["targets"]

    def body() -> Iterator[bytes]:
        for _ in range(9):
            yield b"x" * (1024 * 1024)

    response = api.client.put(
        target["upload_url"],
        content=body(),
        headers={"Content-Range": f"bytes 0-{9 * 1024 * 1024 - 1}/{9 * 1024 * 1024}"},
    )
    assert response.status_code == 413


def test_an_order_id_with_a_trailing_newline_is_not_an_id(api: Api) -> None:
    order_id, auth = new_order(api)
    assert api.client.get(f"/api/orders/{order_id}%0A", headers=auth).status_code == 404


@pytest.mark.parametrize("path", ["/", "/privacy", "/new"])
def test_head_requests_are_answered(api: Api, path: str) -> None:
    assert api.client.head(path).status_code == 200
