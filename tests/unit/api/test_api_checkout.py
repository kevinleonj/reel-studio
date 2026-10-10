"""GET /api/config, POST /api/checkout with PAYMENTS=off (docs/ARCHITECTURE.md §7)."""

import hashlib
import logging
import re
from datetime import timedelta
from pathlib import Path

import pytest

from reel_studio.settings import WebSettings
from tests.conftest import MakeSettings
from tests.unit.api.conftest import Api, build

SETTINGS = {
    "style": "recipe",
    "length_s": 30,
    "text_lang": "en",
    "keep_voice": False,
    "chips": [],
    "note": "",
}
ORDER_URL = re.compile(r"^/o/(?P<id>[0-9a-f]{32})#t=(?P<token>[A-Za-z0-9_-]{40,})$")


def checkout(api: Api, **changes: object) -> tuple[int, dict[str, object]]:
    body: dict[str, object] = {"settings": SETTINGS, "code": "", "email": "", **changes}
    response = api.client.post("/api/checkout", json=body)
    return response.status_code, response.json()


def test_health(api: Api) -> None:
    response = api.client.get("/health")
    assert response.status_code == 200
    assert response.text == "ok"


def test_config_carries_the_web_contract(api: Api) -> None:
    config = api.client.get("/api/config").json()
    assert config["payments"] == "off"
    assert config["voice_available"] is True
    assert [s["key"] for s in config["styles"]] == [
        "montage",
        "recipe",
        "long_take",
        "talking",
        "tutorial",
    ]
    assert config["chips"]["exclusive"] == [["Calm pace", "Fast pace"]]
    assert config["lengths_s"] == [15, 30, 60, 90] and config["default_length_s"] == 30
    assert config["text_languages"] == ["en", "es"]
    assert config["note_max_chars"] == 200
    assert (
        config["limits"]["max_files"] == 40 and config["limits"]["max_total_bytes"] == 4_000_000_000
    )
    assert config["upload"] == {
        "chunk_bytes": 8 * 1024 * 1024,
        "parallel_files": 2,
        "chunk_retries": 5,
        "backoff_ms": 1000,
    }
    assert config["timeouts"] == {"request_ms": 15000, "chunk_ms": 90000}
    assert config["poll_seconds"] == 5
    assert config["feedback"] == {"rating_max": 5, "comment_max_chars": 1000}
    assert config["price"] is None
    assert config["analytics"] == {"enabled": False, "ga4_id": "", "ads_id": "", "tag_url": ""}


def test_config_turns_analytics_on_with_a_measurement_id(
    tmp_path: Path, make_settings: MakeSettings
) -> None:
    settings = make_settings(WebSettings, payments="off", ga4_measurement_id="G-ABC123")
    assert isinstance(settings, WebSettings)
    analytics = build(tmp_path, settings).client.get("/api/config").json()["analytics"]
    assert analytics["enabled"] is True and analytics["ga4_id"] == "G-ABC123"
    assert analytics["tag_url"].startswith("https://")


def test_checkout_off_creates_a_paid_order_and_returns_its_link(api: Api) -> None:
    status, body = checkout(api)
    assert status == 200
    match = ORDER_URL.match(str(body["order_url"]))
    assert match is not None
    doc = api.orders.get(match["id"])
    assert doc is not None
    assert doc["status"] == "paid"
    assert doc["token_hash"] == hashlib.sha256(match["token"].encode()).hexdigest()
    assert match["token"] not in str(doc)  # only the hash is stored (D18)
    assert api.mailer.sent == []  # no email given, no email sent


def test_checkout_with_an_email_sends_the_link(api: Api) -> None:
    status, body = checkout(api, email="friend@example.test")
    assert status == 200
    [mail] = api.mailer.sent
    assert mail.template == "link" and mail.to == "friend@example.test"
    assert str(body["order_url"]) in mail.text


def test_voice_is_forced_off_without_a_gemini_key(
    tmp_path: Path, make_settings: MakeSettings
) -> None:
    settings = make_settings(WebSettings, payments="off")
    assert isinstance(settings, WebSettings)
    api = build(tmp_path, settings, voice_available=False)
    status, body = checkout(api, settings={**SETTINGS, "keep_voice": True})
    assert status == 200
    match = ORDER_URL.match(str(body["order_url"]))
    assert match is not None
    doc = api.orders.get(match["id"])
    assert doc is not None and doc["settings"]["keep_voice"] is False  # type: ignore[index]


@pytest.mark.parametrize(
    "settings",
    [
        {**SETTINGS, "style": "vlog"},
        {**SETTINGS, "length_s": 45},
        {**SETTINGS, "text_lang": "fr"},
        {**SETTINGS, "chips": ["Calm pace", "Fast pace"]},
        {**SETTINGS, "chips": ["Add music"]},
        {**SETTINGS, "note": "x" * 201},
        {k: v for k, v in SETTINGS.items() if k != "style"},
    ],
)
def test_settings_outside_the_config_are_refused(api: Api, settings: dict[str, object]) -> None:
    status, _ = checkout(api, settings=settings)
    assert status == 422
    assert api.orders.orders == {}


def test_the_week_fills(api: Api) -> None:
    for _ in range(3):  # LIMITS.weekly_cap in the test wiring
        assert checkout(api)[0] == 200
    assert checkout(api) == (409, {"error": "week_full"})


def test_checkout_is_rate_limited_per_address(tmp_path: Path, make_settings: MakeSettings) -> None:
    settings = make_settings(WebSettings, payments="off")
    assert isinstance(settings, WebSettings)
    api = build(tmp_path, settings, weekly_cap=100)  # the week must not fill first
    codes = [checkout(api)[0] for _ in range(11)]
    assert codes == [200] * 10 + [429]
    assert checkout(api)[1] == {"error": "rate_limited"}
    api.clock.advance(timedelta(minutes=1, seconds=1))
    assert checkout(api)[0] == 200


def test_stripe_checkout_is_not_wired_in_this_step(
    tmp_path: Path, make_settings: MakeSettings
) -> None:
    settings = make_settings(
        WebSettings,
        payments="stripe",
        stripe_secret_key="sk_test_x",
        stripe_webhook_secret="whsec_x",
    )
    assert isinstance(settings, WebSettings)
    response = build(tmp_path, settings).client.post(
        "/api/checkout", json={"settings": SETTINGS, "code": "C", "email": ""}
    )
    assert response.status_code == 501
    assert response.json() == {"error": "payments_not_wired"}


def test_logs_never_carry_the_token(api: Api, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="reel_studio")
    _, body = checkout(api, email="friend@example.test")
    match = ORDER_URL.match(str(body["order_url"]))
    assert match is not None
    api.client.get(f"/api/orders/{match['id']}", headers={"X-Order-Token": match["token"]})
    for record in caplog.records:
        assert match["token"] not in record.getMessage()
        assert match["token"] not in str(record.__dict__)
        assert "friend@example.test" not in str(record.__dict__)
