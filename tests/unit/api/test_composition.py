"""The laptop composition root (STEP-06 task 6): settings in, a working API and dispatcher out.
Firestore is replaced by the fake here; the real client is built only by `firestore_orders`."""

import io
import runpy
import time
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reel_studio.adapters.launcher_local import Dispatcher
from reel_studio.adapters.mailer_smtp import SmtpMailer
from reel_studio.api import main
from reel_studio.api.app import create_app
from reel_studio.api.main import build_deps, build_dispatcher
from reel_studio.api.routes_local import UPLOAD_PATH
from reel_studio.core.config import Config, load
from reel_studio.core.ports import NewOrder
from reel_studio.settings import WebSettings
from tests.conftest import MakeSettings
from tests.fakes.clock import FrozenClock
from tests.fakes.orders import FakeOrders
from tests.unit.api.conftest import LIMITS, START

SETTINGS = {"style": "recipe", "length_s": 30, "text_lang": "en", "keep_voice": False}
SHELL = "<div>new shell</div>"
WAIT_S = 5.0
POLL_S = 0.01
WEB_NAMES = {f"{name.upper()}" for name in WebSettings.model_fields}


def quick_config() -> Config:
    """The repository's config with the fake editor's pauses at zero."""
    config = load()
    limits = config.limits
    dispatcher = limits.dispatcher.model_copy(update={"fake_stage_seconds": 0})
    return config.model_copy(
        update={"limits": limits.model_copy(update={"dispatcher": dispatcher})}
    )


def laptop(tmp_path: Path, make_settings: MakeSettings, **changes: object) -> WebSettings:
    dist = tmp_path / "dist"
    (dist / "new").mkdir(parents=True)
    (dist / "new" / "index.html").write_text(SHELL)
    values: dict[str, object] = {
        "payments": "off",
        "firestore_project": "reel-studio-test",
        "smtp_host": "mailpit",
        "smtp_port": 1025,
        "data_dir": tmp_path / "data",
        "web_dist": dist,
        "voice_available": False,
        **changes,
    }
    settings = make_settings(WebSettings, **values)
    assert isinstance(settings, WebSettings)
    return settings


def test_the_api_is_wired_from_settings(tmp_path: Path, make_settings: MakeSettings) -> None:
    settings = laptop(tmp_path, make_settings)
    clock = FrozenClock(START)
    deps = build_deps(settings, orders=FakeOrders(clock, LIMITS), clock=clock, config=load())
    assert isinstance(deps.mailer, SmtpMailer)
    assert deps.web_dist == settings.web_dist
    assert deps.voice_available is False
    client = TestClient(create_app(deps))
    assert client.get("/health").text == "ok"
    assert client.get("/api/config").json()["payments"] == "off"
    assert client.get("/new").text == SHELL
    body = {
        "settings": {**SETTINGS, "chips": [], "note": ""},
        "code": "",
        "email": "",
    }
    order_url = client.post("/api/checkout", json=body).json()["order_url"]
    order_id, token = order_url.removeprefix("/o/").split("#t=")
    targets = client.post(
        f"/api/orders/{order_id}/uploads",
        json={"files": [{"name": "a.mp4", "size": 1, "type": "video/mp4"}]},
        headers={"X-Order-Token": token},
    ).json()
    assert targets["targets"][0]["upload_url"].startswith(f"{UPLOAD_PATH}/")
    assert (settings.data_dir).is_dir()


def test_stripe_is_refused_until_its_adapter_exists(
    tmp_path: Path, make_settings: MakeSettings
) -> None:
    settings = laptop(
        tmp_path,
        make_settings,
        payments="stripe",
        stripe_secret_key="test-stripe-key",
        stripe_webhook_secret="test-webhook-secret",
        stripe_price_id="price_test",
        stripe_coupon_id="coupon_test",
    )
    clock = FrozenClock(START)
    with pytest.raises(SystemExit, match="PAYMENTS=stripe"):
        build_deps(settings, orders=FakeOrders(clock, LIMITS), clock=clock, config=load())


def test_the_dispatcher_launches_a_queued_order(
    tmp_path: Path, make_settings: MakeSettings
) -> None:
    settings = laptop(tmp_path, make_settings)
    clock = FrozenClock(START)
    orders = FakeOrders(clock, LIMITS)
    order_id = f"{1:032x}"
    orders.create_awaiting_payment(
        NewOrder(order_id, "h", SETTINGS, "", START + timedelta(minutes=31))
    )
    orders.mark_paid(order_id, {})
    orders.set_manifest(order_id, files=[], bytes_declared=0)
    orders.queue(order_id)
    dispatcher = build_dispatcher(settings, orders=orders, clock=clock, config=quick_config())
    assert isinstance(dispatcher, Dispatcher)
    dispatcher.tick()
    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline and (orders.get(order_id) or {})["status"] != "done":
        time.sleep(POLL_S)
    doc = orders.get(order_id)
    assert doc is not None and doc["status"] == "done"  # the fake editor ran every stage
    assert doc["stages_done"] == ["reading", "planning", "rendering", "checking", "saving"]


def test_a_chunk_and_a_signed_download_go_through_the_composed_routes(
    tmp_path: Path, make_settings: MakeSettings
) -> None:
    settings = laptop(tmp_path, make_settings)
    clock = FrozenClock(START)
    deps = build_deps(settings, orders=FakeOrders(clock, LIMITS), clock=clock, config=load())
    client = TestClient(create_app(deps))
    body = {"settings": {**SETTINGS, "chips": [], "note": ""}, "code": "", "email": ""}
    order_id, token = (
        client.post("/api/checkout", json=body).json()["order_url"].removeprefix("/o/").split("#t=")
    )
    content = b"clip"
    files = {"files": [{"name": "a.mp4", "size": len(content), "type": "video/mp4"}]}
    target = client.post(
        f"/api/orders/{order_id}/uploads", json=files, headers={"X-Order-Token": token}
    ).json()["targets"][0]["upload_url"]
    put = client.put(target, content=content, headers={"Content-Range": "bytes 0-3/4"})
    assert put.status_code == 200
    (key,) = [f["key"] for f in deps.storage.list_inputs(order_id)]
    link = deps.storage.signed_url(str(key), "a.mp4", 1)
    assert client.get(link).content == content


def test_check_names_what_is_missing_without_printing_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in WEB_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PAYMENTS", "off")
    monkeypatch.setenv("SITE_URL", "http://example.test")
    monkeypatch.setenv("KEVIN_ALERT_EMAIL", "")  # blank counts as missing (env_ignore_empty)
    monkeypatch.setenv("SMTP_PORT", "not-a-port-value")
    out = io.StringIO()
    assert main.check(out) == 2
    report = out.getvalue()
    assert "KEVIN_ALERT_EMAIL" in report
    assert "SMTP_PORT" in report
    assert "not-a-port-value" not in report
    assert "http://example.test" not in report


def test_check_passes_a_complete_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    values = {
        "PAYMENTS": "off",
        "SITE_URL": "http://example.test",
        "MAIL_FROM": "reels@example.test",
        "KEVIN_ALERT_EMAIL": "kevin@example.test",
        "FIRESTORE_PROJECT": "reel-studio-test",
        "SMTP_HOST": "mailpit",
        "SMTP_PORT": "1025",
        "DATA_DIR": str(tmp_path),
        "WEB_DIST": str(tmp_path),
        "VOICE_AVAILABLE": "false",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    out = io.StringIO()
    assert main.check(out) == 0


@pytest.mark.filterwarnings("ignore:.*found in sys.modules:RuntimeWarning")  # runpy, expected
def test_the_entry_module_logs_under_the_configured_namespace() -> None:
    """Under `python -m` the module runs as __main__, outside the `reel_studio` logger tree
    that `configure()` wires; run it under another name the same way."""
    namespace = runpy.run_module("reel_studio.api.main", run_name="as_if_dash_m")
    assert namespace["log"].name == "reel_studio.api.main"
