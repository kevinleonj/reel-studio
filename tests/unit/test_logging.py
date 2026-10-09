"""Logs are JSON lines with the D74 fields."""

import io
import json
import logging

from reel_studio.core.logging import D74_FIELDS, configure, get_logger


def _capture() -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    configure(level=logging.DEBUG, stream=stream)
    return get_logger("reel_studio.test"), stream


def _lines(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_event_carries_every_d74_field() -> None:
    log, stream = _capture()
    context = {
        "order_id": "o1",
        "stage": "render",
        "event": "render_done",
        "latency_ms": 1234,
        "outcome": "ok",
    }

    log.info("render finished in %s passes", 2, extra=context)

    [line] = _lines(stream)
    assert line["message"] == "render finished in 2 passes"
    assert {k: line[k] for k in D74_FIELDS} == context


def test_missing_fields_are_null() -> None:
    log, stream = _capture()

    log.warning("no context")

    [line] = _lines(stream)
    assert all(line[k] is None for k in D74_FIELDS)
    assert line["level"] == "WARNING"


def test_many_events_are_one_line_each() -> None:
    log, stream = _capture()

    for n in range(3):
        log.info("line %s\nwith a newline", n)

    assert len(_lines(stream)) == 3


def test_exception_is_named_not_dumped() -> None:
    log, stream = _capture()

    try:
        raise ValueError("boom")
    except ValueError:
        log.exception("failed", extra={"event": "crash", "outcome": "error"})

    [line] = _lines(stream)
    assert line["error_type"] == "ValueError"
    assert "Traceback" in str(line["traceback"])
