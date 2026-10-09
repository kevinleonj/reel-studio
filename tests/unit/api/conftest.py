"""An API wired to fakes, a filesystem Storage in tmp and a fake built site."""

from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reel_studio.adapters.storage_local import LocalStorage
from reel_studio.api.app import ApiDeps, create_app
from reel_studio.core.config import load
from reel_studio.core.ports import QueueLimits
from reel_studio.settings import WebSettings
from tests.conftest import MakeSettings
from tests.fakes.clock import FrozenClock
from tests.fakes.mailer import FakeMailer
from tests.fakes.orders import FakeOrders

START = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
LIMITS = QueueLimits(
    running_max=2, lease_minutes=70, weekly_cap=3, paid_not_started_days=7, expiry_grace_minutes=5
)
SITE_FILES = {
    "index.html": "<h1>landing</h1>",
    "privacy/index.html": "<h1>privacy</h1>",
    "new/index.html": "<div>new shell</div>",
    "o/index.html": "<div>order shell</div>",
    "404.html": "<h1>not found</h1>",
    "robots.txt": "User-agent: *",
    "sitemap-index.xml": "<sitemapindex/>",
    "_astro/app.abc123.js": "console.log(1)",
}


@dataclass
class Api:
    client: TestClient
    orders: FakeOrders
    storage: LocalStorage
    mailer: FakeMailer
    clock: FrozenClock


def build(
    tmp_path: Path,
    settings: WebSettings,
    *,
    voice_available: bool = True,
    weekly_cap: int = LIMITS.weekly_cap,
) -> Api:
    dist = tmp_path / "dist"
    for name, body in SITE_FILES.items():
        (dist / name).parent.mkdir(parents=True, exist_ok=True)
        (dist / name).write_text(body)
    clock = FrozenClock(START)
    orders = FakeOrders(clock, replace(LIMITS, weekly_cap=weekly_cap))
    storage = LocalStorage(
        tmp_path / "data",
        upload_path="/api/local-upload",
        download_path="/api/local-files",
        signing_key=b"k" * 32,
        clock=clock,
    )
    mailer = FakeMailer()
    deps = ApiDeps(
        orders=orders,
        storage=storage,
        local_storage=storage,
        mailer=mailer,
        clock=clock,
        config=load(),
        settings=settings,
        voice_available=voice_available,
        web_dist=dist,
    )
    return Api(TestClient(create_app(deps)), orders, storage, mailer, clock)


@pytest.fixture
def api(tmp_path: Path, make_settings: MakeSettings) -> Iterator[Api]:
    settings = make_settings(WebSettings, payments="off")
    assert isinstance(settings, WebSettings)
    yield build(tmp_path, settings)
