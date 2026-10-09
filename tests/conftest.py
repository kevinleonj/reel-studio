"""Isolation for every test: no network, no .env, no real environment values.

- Unit tests cannot open a connection, resolve a name, send a datagram or open a gRPC channel
  (tests marked emulator, e2e or paid may). Raw C sockets opened by other native libraries are
  not covered.
- Every variable a Settings class reads, and Google's credential variables, are removed.
- Each test runs in its own empty folder, so the repository's `.env` is never read.
- `make_settings` builds Settings from explicit test values with `_env_file=None`.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from reel_studio.settings import AppSettings
from tests.fakes import environment, network

TEST_VALUES: dict[str, Any] = {
    "anthropic_api_key": "test-anthropic-key",
    "gemini_api_key": "test-gemini-key",
    "ffmpeg_path": "/nonexistent/bin/ffmpeg",
    "ffprobe_path": "/nonexistent/bin/ffprobe",
    "old_kit_dir": "/nonexistent/old-kit",
    "reel_fixtures_dir": "/nonexistent/fixtures",
    "payments": "off",
    "site_url": "http://127.0.0.1:8000",
    "mail_from": "reels@example.test",
    "kevin_alert_email": "kevin@example.test",
    "gcp_project": "test-project",
    "gcp_region": "test-region",
    "gcp_billing_account": "000000-000000-000000",
    "cloud_anthropic_api_key": "test-cloud-anthropic-key",
    "cloud_gemini_api_key": "test-cloud-gemini-key",
    "resend_api_key": "test-resend-key",
    "cloudflare_api_token": "test-cloudflare-token",
    "email_domain": "example.test",
}

MakeSettings = Callable[..., AppSettings]


@pytest.fixture(autouse=True)
def _no_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if network.is_exempt(marker.name for marker in request.node.iter_markers()):
        return
    network.block(monkeypatch)


@pytest.fixture(autouse=True)
def _no_real_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    environment.scrub(monkeypatch)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def make_settings() -> MakeSettings:
    def build(cls: type[AppSettings], **overrides: Any) -> AppSettings:
        values = {k: v for k, v in TEST_VALUES.items() if k in cls.model_fields}
        values.update(overrides)
        return cls(_env_file=None, **values)

    return build
