"""Unit tests cannot spend money or read secrets (STEP-01 task 3)."""

import os
import socket
from collections.abc import Callable
from pathlib import Path

import grpc
import pytest
from pydantic import ValidationError

from reel_studio.settings import EditorSettings
from tests.conftest import MakeSettings
from tests.fakes import environment
from tests.fakes.network import NetworkBlockedError

TEST_NET = ("192.0.2.1", 80)  # RFC 5737 TEST-NET-1: never routed, even if the block failed
TEST_TARGET = "192.0.2.1:443"
ORIGINAL_CREATE_CONNECTION = socket.create_connection


def test_unit_test_cannot_open_a_connection() -> None:
    with pytest.raises(NetworkBlockedError):
        socket.create_connection(TEST_NET)


def test_unit_test_cannot_connect_a_raw_socket() -> None:
    with socket.socket() as sock, pytest.raises(NetworkBlockedError):
        sock.connect(TEST_NET)


def test_unit_test_cannot_connect_ex_a_raw_socket() -> None:
    with socket.socket() as sock, pytest.raises(NetworkBlockedError):
        sock.connect_ex(TEST_NET)


def test_unit_test_cannot_send_a_datagram() -> None:
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock,
        pytest.raises(NetworkBlockedError),
    ):
        sock.sendto(b"x", TEST_NET)


@pytest.mark.parametrize(
    "resolve",
    [
        lambda: socket.getaddrinfo("api.anthropic.com", 443),
        lambda: socket.gethostbyname("api.anthropic.com"),
        lambda: socket.gethostbyname_ex("api.anthropic.com"),
    ],
    ids=["getaddrinfo", "gethostbyname", "gethostbyname_ex"],
)
def test_unit_test_cannot_resolve_a_name(resolve: Callable[[], object]) -> None:
    with pytest.raises(NetworkBlockedError):
        resolve()


@pytest.mark.parametrize(
    "open_channel",
    [
        lambda: grpc.insecure_channel(TEST_TARGET),
        lambda: grpc.secure_channel(TEST_TARGET, grpc.ssl_channel_credentials()),
        lambda: grpc.aio.insecure_channel(TEST_TARGET),
        lambda: grpc.aio.secure_channel(TEST_TARGET, grpc.ssl_channel_credentials()),
    ],
    ids=["insecure", "secure", "aio-insecure", "aio-secure"],
)
def test_unit_test_cannot_open_a_grpc_channel(open_channel: Callable[[], object]) -> None:
    # Firestore and Cloud Run clients speak gRPC through C sockets the Python patches miss.
    with pytest.raises(NetworkBlockedError):
        open_channel()


@pytest.mark.emulator
def test_emulator_test_keeps_the_real_socket() -> None:
    assert socket.create_connection is ORIGINAL_CREATE_CONNECTION


@pytest.mark.e2e
def test_e2e_test_keeps_the_real_socket() -> None:
    assert socket.create_connection is ORIGINAL_CREATE_CONNECTION


@pytest.mark.paid
def test_paid_test_keeps_the_real_socket() -> None:
    assert socket.create_connection is ORIGINAL_CREATE_CONNECTION


def test_settings_ignore_a_dotenv_file_in_the_working_folder(
    make_settings: MakeSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("GEMINI_API_KEY=from-dotenv\n", encoding="utf-8")

    built = make_settings(EditorSettings, gemini_api_key=None)

    assert isinstance(built, EditorSettings)
    assert built.anthropic_api_key.get_secret_value() == "test-anthropic-key"
    assert built.gemini_api_key is None


def test_settings_without_env_file_see_no_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=from-dotenv\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="anthropic_api_key"):
        EditorSettings(_env_file=None)


def test_tests_run_outside_the_repository() -> None:
    assert not (Path.cwd() / "pyproject.toml").exists()


def test_scrub_removes_settings_and_google_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    names = environment.variable_names()
    for name in names:
        monkeypatch.setenv(name, "leaked")

    environment.scrub(monkeypatch)

    assert "ANTHROPIC_API_KEY" in names
    assert "GOOGLE_APPLICATION_CREDENTIALS" in names
    assert not [name for name in names if name in os.environ]
