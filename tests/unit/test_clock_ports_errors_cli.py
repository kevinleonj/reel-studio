"""Clock, ports, errors and the command-line stubs."""

import inspect
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from reel_studio.adapters.clock import SystemClock
from reel_studio.cli import reel, reelctl
from reel_studio.core import errors, ports
from tests.fakes.clock import FrozenClock

START = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)

# docs/ARCHITECTURE.md §3: "Methods (names are binding)"
PORT_METHODS = {
    "Storage": {
        "create_upload_session",
        "list_inputs",
        "download",
        "upload",
        "signed_url",
        "delete_order",
    },
    "Orders": {
        "create_awaiting_payment",
        "mark_paid",
        "expire",
        "set_manifest",
        "queue",
        "take_slot",
        "release_slot",
        "next_queued",
        "set_stage",
        "finish",
        "fail",
        "pause",
        "get",
    },
    "Launcher": {"launch"},
    "Mailer": {"send"},
    "Payments": {"find_code", "create_checkout", "parse_webhook", "get_session"},
    "Claude": {"count_tokens", "create"},
    "Transcriber": {"transcribe"},
    "Clock": {"now"},
}


def test_frozen_clock_stays_until_advanced() -> None:
    clock: ports.Clock = FrozenClock(START)

    assert clock.now() == START
    assert clock.now() == START


def test_frozen_clock_advances() -> None:
    clock = FrozenClock(START)

    clock.advance(timedelta(minutes=5))

    assert clock.now() == START + timedelta(minutes=5)


def test_frozen_clock_refuses_naive_time() -> None:
    with pytest.raises(ValueError, match="timezone"):
        FrozenClock(datetime(2026, 10, 9))  # noqa: DTZ001 - the naive value is the point


def test_system_clock_is_utc() -> None:
    clock: ports.Clock = SystemClock()

    assert clock.now().tzinfo is UTC


@pytest.mark.parametrize(("port", "methods"), sorted(PORT_METHODS.items()))
def test_port_has_the_binding_methods(port: str, methods: set[str]) -> None:
    cls = getattr(ports, port)
    declared = {n for n, _ in inspect.getmembers(cls, inspect.isfunction) if not n.startswith("_")}

    assert declared == methods


def _concrete_errors() -> list[type[errors.ReelError]]:
    found: list[type[errors.ReelError]] = []
    pending = list(errors.ReelError.__subclasses__())
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        if cls not in errors.BOUNDARIES:
            found.append(cls)
    return found


def test_every_error_has_a_unique_snake_case_code() -> None:
    concrete = _concrete_errors()
    codes = [cls.code for cls in concrete]

    assert concrete
    assert len(codes) == len(set(codes))
    assert all(re.fullmatch(r"[a-z]+(_[a-z]+)*", code) for code in codes)


def test_every_error_belongs_to_one_boundary() -> None:
    for cls in _concrete_errors():
        assert sum(issubclass(cls, b) for b in errors.BOUNDARIES) == 1, cls.__name__


def test_error_keeps_its_detail() -> None:
    err = errors.RenderError("ffmpeg exited 1")

    assert err.code == errors.ErrorCode.RENDER_ERROR
    assert "ffmpeg exited 1" in str(err)


@pytest.mark.parametrize(("main", "name"), [(reel.main, "reel"), (reelctl.main, "reelctl")])
def test_cli_stub_prints_usage(
    main: Callable[[list[str]], int], name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main([])

    assert code == 0
    assert f"usage: {name}" in capsys.readouterr().out
