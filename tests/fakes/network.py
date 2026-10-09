"""Blocks outbound traffic so a unit test can never reach a paid API.

Covers the standard library's sockets and name lookups, and gRPC channel creation (the transport
of the Firestore and Cloud Run clients, whose C core opens its own sockets). Other native
libraries that open raw sockets are not covered.
"""

import socket
from typing import NoReturn

import grpc
import pytest

EXEMPT_MARKERS = ("emulator", "e2e", "paid")


class NetworkBlockedError(RuntimeError):
    """A unit test tried to open a network connection."""


def _refuse(*_args: object, **_kwargs: object) -> NoReturn:
    raise NetworkBlockedError(
        "unit tests cannot open network connections; mark the test emulator, e2e or paid"
    )


def block(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace every way a test could open a connection, send a datagram or resolve a name."""
    for name in ("connect", "connect_ex", "sendto", "sendmsg"):
        monkeypatch.setattr(socket.socket, name, _refuse)
    for name in ("create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex"):
        monkeypatch.setattr(socket, name, _refuse)
    for module in (grpc, grpc.aio):
        monkeypatch.setattr(module, "insecure_channel", _refuse)
        monkeypatch.setattr(module, "secure_channel", _refuse)
