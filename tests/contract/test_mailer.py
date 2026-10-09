"""Contract for the Mailer port: the fake and SMTP to Mailpit (marker `emulator`)."""

import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import httpx
import pytest

from reel_studio.adapters.mailer_smtp import SmtpMailer
from reel_studio.core.ports import Mailer
from tests.contract.firestore_emulator import REQUIRE_ENV
from tests.fakes.mailer import FakeMailer

MAILPIT_ENV = "MAILPIT_HOST"  # host:smtp_port,http_port, set by tests/contract/run_emulator.py
TIMEOUT_S = 10.0
DATA = {
    "order_url": "http://127.0.0.1:8080/o/x#t=y",
    "max_files": 40,
    "max_total": "4 GB",
    "out_days": 30,
}


@dataclass(frozen=True)
class Inbox:
    mailer: Mailer
    read: Callable[[], list[dict[str, str]]]


@pytest.fixture(params=["fake", pytest.param("mailpit", marks=pytest.mark.emulator)])
def inbox(request: pytest.FixtureRequest) -> Iterator[Inbox]:
    if request.param == "fake":
        fake = FakeMailer()
        yield Inbox(fake, lambda: [{"to": m.to, "subject": m.subject} for m in fake.sent])
        return
    spec = os.environ.get(MAILPIT_ENV)
    if not spec:
        if os.environ.get(REQUIRE_ENV) == "1":  # make test-emulator: a skip would be a failure
            pytest.fail(f"{MAILPIT_ENV} is not set but the emulators are required")
        pytest.skip(f"{MAILPIT_ENV} is not set: run `make test-emulator`")
    host, ports = spec.split(":")
    smtp_port, http_port = (int(p) for p in ports.split(","))
    api = f"http://{host}:{http_port}/api/v1/messages"
    httpx.delete(api, timeout=TIMEOUT_S).raise_for_status()

    def read() -> list[dict[str, str]]:
        messages = httpx.get(api, timeout=TIMEOUT_S).raise_for_status().json()["messages"]
        return [{"to": m["To"][0]["Address"], "subject": m["Subject"]} for m in messages]

    yield Inbox(
        SmtpMailer(host, smtp_port, sender="Reel Studio <reels@localhost>", timeout_s=TIMEOUT_S),
        read,
    )


def test_nothing_sent_nothing_received(inbox: Inbox) -> None:
    assert inbox.read() == []


def test_one_email_arrives_with_its_subject(inbox: Inbox) -> None:
    inbox.mailer.send("link", "friend@example.test", DATA)
    assert inbox.read() == [{"to": "friend@example.test", "subject": "Your Reel Studio link"}]


def test_unknown_template_is_refused(inbox: Inbox) -> None:
    with pytest.raises(KeyError):
        inbox.mailer.send("nope", "friend@example.test", DATA)
    assert inbox.read() == []
