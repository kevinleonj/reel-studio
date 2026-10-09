"""Unit tests cannot spend money or read secrets (STEP-01 task 3)."""

import os
import socket
from collections.abc import Callable
from pathlib import Path

import grpc
import pytest
from pydantic import ValidationError

from reel_studio.settings import ENV_FILE, EditorSettings, WebSettings
from tests.conftest import MakeSettings
from tests.fakes import environment, network
from tests.fakes.network import NetworkBlockedError

TEST_NET = ("192.0.2.1", 80)  # RFC 5737 TEST-NET-1: never routed, even if the block failed
TEST_TARGET = "192.0.2.1:443"
FAIL_FAST_S = 0.1
ORIGINAL_CREATE_CONNECTION = socket.create_connection


def _socket(kind: int = socket.SOCK_STREAM) -> socket.socket:
    sock = socket.socket(socket.AF_INET, kind)
    sock.settimeout(FAIL_FAST_S)  # if the block regresses, fail fast instead of hanging
    return sock


def test_unit_test_cannot_open_a_connection() -> None:
    with pytest.raises(NetworkBlockedError):
        socket.create_connection(TEST_NET, timeout=FAIL_FAST_S)


def test_unit_test_cannot_connect_a_raw_socket() -> None:
    with _socket() as sock, pytest.raises(NetworkBlockedError):
        sock.connect(TEST_NET)


def test_unit_test_cannot_connect_ex_a_raw_socket() -> None:
    with _socket() as sock, pytest.raises(NetworkBlockedError):
        sock.connect_ex(TEST_NET)


@pytest.mark.parametrize(
    "send",
    [
        lambda sock: sock.sendto(b"x", TEST_NET),
        lambda sock: sock.sendmsg([b"x"], [], 0, TEST_NET),
    ],
    ids=["sendto", "sendmsg"],
)
def test_unit_test_cannot_send_a_datagram(send: Callable[[socket.socket], object]) -> None:
    with _socket(socket.SOCK_DGRAM) as sock, pytest.raises(NetworkBlockedError):
        send(sock)


@pytest.mark.parametrize(
    ("markers", "exempt"),
    [((), False), (("slow",), False), (("paid",), True), (("e2e",), True), (("emulator",), True)],
)
def test_only_marked_tests_may_use_the_network(markers: tuple[str, ...], exempt: bool) -> None:
    # The paid test below is deselected by every make target, so the rule is pinned here too.
    assert network.is_exempt(markers) is exempt


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
    # A field the factory does not pass, so only the dotenv file could set it.
    monkeypatch.chdir(tmp_path)
    (tmp_path / ENV_FILE).write_text("GA4_MEASUREMENT_ID=from-dotenv\n", encoding="utf-8")

    built = make_settings(WebSettings)

    assert isinstance(built, WebSettings)
    assert built.ga4_measurement_id == ""


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

    assert {"ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "GOOGLE_APPLICATION_CREDENTIALS"} <= set(
        names
    )
    assert {"GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI", "GCLOUD_PROJECT"} <= set(names)
    assert not [name for name in names if name in os.environ]
