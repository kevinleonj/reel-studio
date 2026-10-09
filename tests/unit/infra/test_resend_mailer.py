"""ResendMailer: the cloud Mailer, over Resend's REST API with httpx (no SDK dependency)."""

import json
import logging

import httpx
import pytest
from pydantic import SecretStr

from reel_studio.adapters.resend_mailer import Backoff, Email, ResendConfig, ResendMailer
from reel_studio.core import ports
from reel_studio.core.errors import CloudUnavailable

API = "https://resend.test"
KEY = "test-resend-key"
SENDER = "Reel Studio <reels@example.test>"
RETRIES = 2
BACKOFF_S = 0.5


def render(template: str, data: ports.Record) -> Email:
    return Email(subject=f"{template} {data['order_id']}", html="<p>hi</p>", text="hi")


class Recorder:
    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def make(recorder: Recorder, sleeps: list[float]) -> ResendMailer:
    client = httpx.Client(base_url=API, transport=httpx.MockTransport(recorder))
    return ResendMailer(
        client,
        ResendConfig(api_key=SecretStr(KEY), sender=SENDER),
        render,
        Backoff(retries=RETRIES, base_s=BACKOFF_S, sleep=sleeps.append),
    )


def ok() -> httpx.Response:
    return httpx.Response(200, json={"id": "email-1"})


def test_satisfies_the_port() -> None:
    mailer: ports.Mailer = make(Recorder(), [])
    assert mailer is not None


def test_one_email_is_posted_with_auth_and_idempotency_key() -> None:
    recorder = Recorder(ok())

    make(recorder, []).send("ready", "friend@example.test", {"order_id": "o1"})

    [request] = recorder.requests
    assert request.method == "POST"
    assert request.url == httpx.URL(f"{API}/emails")
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert 1 <= len(request.headers["Idempotency-Key"]) <= 256
    assert json.loads(request.content) == {
        "from": SENDER,
        "to": ["friend@example.test"],
        "subject": "ready o1",
        "html": "<p>hi</p>",
        "text": "hi",
    }


def test_same_email_gets_the_same_key_and_different_emails_differ() -> None:
    recorder = Recorder(ok(), ok(), ok())
    mailer = make(recorder, [])

    mailer.send("ready", "a@example.test", {"order_id": "o1"})
    mailer.send("ready", "a@example.test", {"order_id": "o1"})
    mailer.send("failed", "a@example.test", {"order_id": "o1"})

    keys = [r.headers["Idempotency-Key"] for r in recorder.requests]
    assert keys[0] == keys[1] != keys[2]


@pytest.mark.parametrize(
    "transient",
    [
        httpx.Response(429, json={"name": "rate_limit_exceeded"}),
        httpx.Response(503, json={"name": "internal_server_error"}),
        httpx.Response(409, json={"name": "concurrent_idempotent_requests"}),
        httpx.ReadTimeout("slow"),
    ],
    ids=["429", "503", "409-concurrent", "timeout"],
)
def test_transient_failure_is_retried_with_backoff(transient: httpx.Response | Exception) -> None:
    recorder = Recorder(transient, ok())
    sleeps: list[float] = []

    make(recorder, sleeps).send("ready", "a@example.test", {"order_id": "o1"})

    assert len(recorder.requests) == 2
    assert sleeps == [BACKOFF_S]
    assert len({r.headers["Idempotency-Key"] for r in recorder.requests}) == 1


def test_retries_are_bounded_then_cloud_unavailable() -> None:
    recorder = Recorder(*[httpx.Response(503, json={})] * (RETRIES + 1))
    sleeps: list[float] = []

    with pytest.raises(CloudUnavailable, match="503"):
        make(recorder, sleeps).send("ready", "a@example.test", {"order_id": "o1"})

    assert len(recorder.requests) == RETRIES + 1
    assert sleeps == [BACKOFF_S, BACKOFF_S * 2]


@pytest.mark.parametrize(
    "permanent",
    [
        httpx.Response(422, json={"name": "validation_error"}),
        httpx.Response(409, json={"name": "invalid_idempotent_request"}),
        httpx.Response(403, json={"name": "invalid_api_key"}),
    ],
    ids=["422", "409-invalid", "403"],
)
def test_permanent_failure_is_not_retried(permanent: httpx.Response) -> None:
    recorder = Recorder(permanent)

    with pytest.raises(CloudUnavailable):
        make(recorder, []).send("ready", "a@example.test", {"order_id": "o1"})

    assert len(recorder.requests) == 1


def test_logs_carry_latency_but_never_the_key_or_address(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        make(Recorder(ok()), []).send("ready", "friend@example.test", {"order_id": "o1"})

    [record] = [r for r in caplog.records if r.name.endswith("resend_mailer")]
    dumped = json.dumps(record.__dict__, default=str)
    assert record.__dict__["order_id"] == "o1"
    assert record.__dict__["outcome"] == "ok"
    assert isinstance(record.__dict__["latency_ms"], int)
    assert KEY not in dumped
    assert "friend@example.test" not in dumped
