"""Isolation for every test: no network, no .env, no real environment values.

- Unit tests cannot open a connection (tests marked emulator, e2e or paid may).
- Every variable a Settings class reads is removed from the environment.
- Each test runs in its own empty folder, so the repository's `.env` is never read.
- `make_settings` builds Settings from explicit test values with `_env_file=None`.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from reel_studio.settings import SETTINGS_CLASSES, AppSettings
from tests.fakes import network

TEST_VALUES: dict[str, Any] = {
    "anthropic_api_key": "test-anthropic-key",
    "gemini_api_key": "test-gemini-key",
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
    if any(request.node.get_closest_marker(name) for name in network.EXEMPT_MARKERS):
        return
    network.block(monkeypatch)


@pytest.fixture(autouse=True)
def _no_real_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for cls in SETTINGS_CLASSES:
        for field in cls.model_fields:
            monkeypatch.delenv(field.upper(), raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def make_settings() -> MakeSettings:
    def build(cls: type[AppSettings], **overrides: Any) -> AppSettings:
        values = {k: v for k, v in TEST_VALUES.items() if k in cls.model_fields}
        values.update(overrides)
        return cls(_env_file=None, **values)

    return build
