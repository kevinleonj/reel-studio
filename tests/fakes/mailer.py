"""Mailer port that keeps the rendered emails in memory."""

from collections.abc import Mapping
from dataclasses import dataclass

from reel_studio.adapters.mailer_smtp import render


@dataclass(frozen=True)
class SentMail:
    template: str
    to: str
    subject: str
    text: str
    data: Mapping[str, object]


class FakeMailer:
    def __init__(self) -> None:
        self.sent: list[SentMail] = []

    def send(self, template: str, to: str, data: Mapping[str, object]) -> None:
        mail = render(template, data)  # same templates, so a bad one fails here too
        self.sent.append(SentMail(template, to, mail.subject, mail.text, dict(data)))
