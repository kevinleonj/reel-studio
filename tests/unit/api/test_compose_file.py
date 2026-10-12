"""compose.yaml's safety properties (STEP-06 task 6 review): read as text, because the file is
small and flat and a YAML parser would be one more dependency for five assertions."""

import re
from pathlib import Path

from reel_studio.settings import WebSettings

COMPOSE = Path(__file__).resolve().parents[3] / "compose.yaml"
SERVICES = ("api", "dispatcher", "firestore", "mailpit")
COMPOSE_ONLY = {"FIRESTORE_EMULATOR_HOST"}  # the Google client reads it itself (F308)


def text() -> str:
    return COMPOSE.read_text()


def service(name: str) -> str:
    """The block of one service: from its header to the next service header."""
    blocks = re.split(r"^  (?=[a-z]+:\n)", text(), flags=re.M)
    found = [b for b in blocks if b.startswith(f"{name}:\n")]
    assert len(found) == 1, name
    return found[0]


def test_no_service_gets_the_whole_settings_file() -> None:
    """D62: the website never holds the Anthropic or Gemini key; each name is passed on purpose."""
    assert not re.search(r"^\s+env_file:", text(), flags=re.M)


def test_the_website_receives_exactly_its_settings() -> None:
    block = text().split("x-website-settings:", 1)[1].split("\nservices:", 1)[0]
    listed = re.findall(r"^  ([A-Z][A-Z0-9_]*):", block, flags=re.M)
    # Compose refuses a repeated key (PyYAML would quietly keep the last): STEP-07 review round 2.
    assert len(listed) == len(set(listed)), sorted(n for n in listed if listed.count(n) > 1)
    assert set(listed) == {f.upper() for f in WebSettings.model_fields} | COMPOSE_ONLY
    for name in ("api", "dispatcher"):
        assert "environment: *website" in service(name), name


def test_only_the_site_is_reachable_from_the_wifi() -> None:
    """D17 needs port 8080 on every interface; the Mailpit inbox holds order links (D18)."""
    published = re.findall(r'^      - "([0-9.:]+)"', text(), flags=re.M)
    public = [p for p in published if not p.startswith("127.0.0.1:")]
    assert public == ["8080:8080"]
    assert '"127.0.0.1:8025:8025"' in service("mailpit")


def test_every_service_comes_back_after_a_restart() -> None:
    for name in SERVICES:
        assert "restart: unless-stopped" in service(name), name


def test_the_app_writes_data_as_the_host_user() -> None:
    """A Linux bind mount belongs to the host user; uid 10001 could not write it."""
    for name in ("api", "dispatcher"):
        assert 'user: "${HOST_UID:-10001}:${HOST_GID:-10001}"' in service(name), name
