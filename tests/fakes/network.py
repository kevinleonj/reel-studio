"""Blocks outbound connections so a unit test can never reach a paid API."""

import socket
from typing import NoReturn

import pytest

EXEMPT_MARKERS = ("emulator", "e2e", "paid")


class NetworkBlockedError(RuntimeError):
    """A unit test tried to open a network connection."""


def _refuse(*_args: object, **_kwargs: object) -> NoReturn:
    raise NetworkBlockedError(
        "unit tests cannot open network connections; mark the test emulator, e2e or paid"
    )


def block(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace every way the standard library opens a connection or resolves a name."""
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    monkeypatch.setattr(socket, "getaddrinfo", _refuse)
