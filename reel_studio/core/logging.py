"""JSON-lines logging (D74).

Every line carries `order_id`, `stage`, `event`, `latency_ms` and `outcome` (null when not given),
passed through `extra=`. Messages use lazy %s formatting. Never log a key, a token, an email body
or a query string.
"""

import json
import logging
import sys
from typing import TextIO

D74_FIELDS = ("order_id", "stage", "event", "latency_ms", "outcome")


class JsonLineFormatter(logging.Formatter):
    """One JSON object per record; an exception adds its type and traceback."""

    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, object] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in D74_FIELDS:
            line[field] = getattr(record, field, None)
        if record.exc_info and record.exc_info[0] is not None:
            line["error_type"] = record.exc_info[0].__name__
            line["traceback"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str)


def configure(level: int = logging.INFO, stream: TextIO | None = None) -> None:
    """Route every reel_studio logger to one JSON-lines handler (stdout unless `stream`)."""
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(JsonLineFormatter())
    root = logging.getLogger("reel_studio")
    root.handlers[:] = [handler]
    root.setLevel(level)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """A module-level named logger: `log = get_logger(__name__)`."""
    return logging.getLogger(name)
