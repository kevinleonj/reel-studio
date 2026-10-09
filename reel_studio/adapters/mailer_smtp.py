"""Mailer port over SMTP: Mailpit on the laptop (F43). Resend replaces it in the cloud (STEP-08).

The five emails of docs/UX.md §3 are Jinja templates in reel_studio/templates/email/: a subject,
a plain-text body and (except Kevin's alert) a small HTML body that reads as text. No images, no
tracking. Values such as the file limit arrive in `data` from config, never in the templates.
"""

import smtplib
import time
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import EmailMessage

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from reel_studio.core.constants import EMAIL_MAX_BYTES, MS_PER_SECOND
from reel_studio.core.errors import DeliveryFailed
from reel_studio.core.logging import get_logger

log = get_logger(__name__)

TEMPLATES = frozenset({"link", "ready", "failed", "paused", "kevin"})
TEXT_ONLY = frozenset({"kevin"})

_env = Environment(
    loader=PackageLoader("reel_studio", "templates"),
    autoescape=select_autoescape(["html"]),
    undefined=StrictUndefined,
    keep_trailing_newline=False,
)


@dataclass(frozen=True)
class Rendered:
    subject: str
    text: str
    html: str | None


def render(template: str, data: Mapping[str, object]) -> Rendered:
    if template not in TEMPLATES:
        raise KeyError(f"no email template {template!r}")
    subject = _env.get_template(f"email/{template}.subject.txt").render(data).strip()
    text = _env.get_template(f"email/{template}.txt").render(data)
    html = (
        None if template in TEXT_ONLY else _env.get_template(f"email/{template}.html").render(data)
    )
    size = len(text.encode()) + len((html or "").encode())
    if size >= EMAIL_MAX_BYTES:
        raise ValueError(f"email {template} is {size} bytes; the limit is {EMAIL_MAX_BYTES}")
    return Rendered(subject, text, html)


class SmtpMailer:
    def __init__(self, host: str, port: int, *, sender: str, timeout_s: float) -> None:
        self._host = host
        self._port = port
        self._sender = sender
        self._timeout_s = timeout_s

    def send(self, template: str, to: str, data: Mapping[str, object]) -> None:
        mail = render(template, data)  # renders before connecting: a bad template sends nothing
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = to
        message["Subject"] = mail.subject
        message.set_content(mail.text)
        if mail.html is not None:
            message.add_alternative(mail.html, subtype="html")
        started = time.monotonic()
        extra = {"order_id": data.get("order_id"), "stage": "mail", "event": template}
        try:
            with smtplib.SMTP(self._host, self._port, timeout=self._timeout_s) as smtp:
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException, ValueError) as error:
            latency = round((time.monotonic() - started) * MS_PER_SECOND)
            log.warning(
                "email %s not sent: %s",
                template,
                type(error).__name__,
                extra={**extra, "latency_ms": latency, "outcome": "error"},
            )
            raise DeliveryFailed(template) from error
        # Never the address or the body (D74, CLAUDE.md): template and latency only.
        latency = round((time.monotonic() - started) * MS_PER_SECOND)
        log.info("email %s sent", template, extra={**extra, "latency_ms": latency, "outcome": "ok"})
