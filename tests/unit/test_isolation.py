"""Unit tests cannot spend money or read secrets (STEP-01 task 3)."""

import os
import socket
from pathlib import Path

import pytest
from pydantic import ValidationError

from reel_studio.settings import EditorSettings
from tests.conftest import MakeSettings
from tests.fakes.network import NetworkBlockedError

TEST_NET = ("192.0.2.1", 80)  # RFC 5737 TEST-NET-1: never routed, even if the block failed
ORIGINAL_CREATE_CONNECTION = socket.create_connection


def test_unit_test_cannot_open_a_connection() -> None:
    with pytest.raises(NetworkBlockedError):
        socket.create_connection(TEST_NET)


def test_unit_test_cannot_connect_a_raw_socket() -> None:
    with socket.socket() as sock, pytest.raises(NetworkBlockedError):
        sock.connect(TEST_NET)


def test_unit_test_cannot_resolve_a_name() -> None:
    with pytest.raises(NetworkBlockedError):
        socket.getaddrinfo("api.anthropic.com", 443)


@pytest.mark.emulator
def test_marked_test_keeps_the_real_socket() -> None:
    assert socket.create_connection is ORIGINAL_CREATE_CONNECTION


def test_settings_ignore_a_dotenv_file(make_settings: MakeSettings) -> None:
    Path(".env").write_text("ANTHROPIC_API_KEY=from-dotenv\nGEMINI_API_KEY=from-dotenv\n")

    built = make_settings(EditorSettings, gemini_api_key=None)

    assert isinstance(built, EditorSettings)
    assert built.anthropic_api_key.get_secret_value() == "test-anthropic-key"
    assert built.gemini_api_key is None


def test_settings_without_env_file_see_no_key() -> None:
    Path(".env").write_text("ANTHROPIC_API_KEY=from-dotenv\n")

    with pytest.raises(ValidationError, match="anthropic_api_key"):
        EditorSettings(_env_file=None)


def test_real_environment_values_are_removed() -> None:
    assert "ANTHROPIC_API_KEY" not in os.environ
