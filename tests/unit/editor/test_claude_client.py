"""The Claude adapter (docs/EDITOR.md §3, D45): our retries, the spend-limit stop, plain JSON out.

The SDK object is a fake that raises the SDK's own exception classes, built on httpx2 requests
and responses (doc ledger: anthropic, httpx2), so no request leaves the process.
"""

import json
import logging
from collections.abc import Callable, Iterator, Sequence
from typing import Any

import anthropic
import httpx2
import pytest
from pydantic import SecretStr

from reel_studio.adapters.claude import client
from reel_studio.core import config
from reel_studio.core.errors import ProviderRejected, ProviderUnavailable, SpendLimitReached

URL = "https://api.anthropic.test/v1/messages"
# Verbatim from https://platform.claude.com/docs/en/api/rate-limits (F13, read 10 Oct 2026).
WORKSPACE_LIMIT = (
    "You have reached your specified workspace API usage limits. "
    "You will regain access on 2026-11-01 at 00:00 UTC."
)
ORGANISATION_LIMIT = (
    "You have reached your specified API usage limits. "
    "You will regain access on 2026-11-01 at 00:00 UTC."
)
TIER_CAP_BODY = {
    "type": "error",
    "error": {
        "type": "rate_limit_error",
        "message": "You have reached your API usage limits: your organization has crossed its "
        "monthly API usage threshold, set based on your organization's API tier. You will "
        "regain access on 2026-09-01 at 00:00 UTC.",
        "details": {"error_code": "enforced_spend_limit_reached"},
    },
}
MESSAGE_MAX = config.load_claude().error_message_max_chars
POLICY = client.RetryPolicy(retries=2, initial_s=0.5, max_s=8.0)
REQUEST: dict[str, Any] = {  # Any: request JSON
    "model": "claude-haiku-5-5",
    "max_tokens": 100,
    "system": "You edit Reels.",
    "messages": [{"role": "user", "content": "Hi"}],
    "tools": [],
    "tool_choice": {"type": "auto"},
    "cache_control": {"type": "ephemeral"},
    "output_config": {"effort": "high"},
}


def body_error(status: int, body: dict[str, Any]) -> anthropic.APIStatusError:  # Any: JSON
    request = httpx2.Request("POST", URL)
    response = httpx2.Response(status, json=body, request=request, headers={"request-id": "r1"})
    return anthropic.APIStatusError(str(body["error"]["message"]), response=response, body=body)


def status_error(status: int, kind: str, message: str = "boom") -> anthropic.APIStatusError:
    return body_error(status, {"type": "error", "error": {"type": kind, "message": message}})


def connection_error() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(request=httpx2.Request("POST", URL))


def timeout_error() -> anthropic.APITimeoutError:
    return anthropic.APITimeoutError(httpx2.Request("POST", URL))


def message() -> anthropic.types.Message:
    reply = anthropic.types.Message.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-haiku-5-5",
            "content": [
                {"type": "text", "text": "Looking."},
                {
                    "type": "tool_use",
                    "id": "tu_1",
                    "name": "read_sheet",
                    "input": {"sheet_id": "s1"},
                },
            ],
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": {
                "input_tokens": 12,
                "output_tokens": 7,
                "cache_creation_input_tokens": 3000,
                "cache_read_input_tokens": 0,
            },
        }
    )
    reply._request_id = "req_123"
    return reply


class _Messages:
    def __init__(self, script: Sequence[object]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []  # Any: request keyword arguments

    def _next(self, kwargs: dict[str, Any]) -> Any:  # Any: what the script holds
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def stream(self, **kwargs: Any) -> "_Stream":  # Any: SDK keyword arguments
        return _Stream(self._next(kwargs))

    def count_tokens(self, **kwargs: Any) -> Any:  # Any: SDK keyword arguments
        return self._next(kwargs)


class _Stream:
    """Stands in for anthropic's MessageStream: a context manager with the final message."""

    def __init__(self, reply: anthropic.types.Message) -> None:
        self.reply = reply
        self.request_id = reply._request_id

    def __enter__(self) -> "_Stream":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get_final_message(self) -> anthropic.types.Message:
        return self.reply


class _Sdk:
    def __init__(self, script: Sequence[object]) -> None:
        self.messages = _Messages(script)


def make(script: Sequence[object]) -> tuple[client.ClaudeClient, _Sdk, list[float]]:
    sdk, sleeps = _Sdk(script), list[float]()
    return client.ClaudeClient(sdk, POLICY, MESSAGE_MAX, sleep=sleeps.append), sdk, sleeps


RETRYABLE = [
    pytest.param(connection_error, id="connection"),
    pytest.param(timeout_error, id="timeout"),
    pytest.param(lambda: status_error(408, "timeout_error"), id="408"),
    pytest.param(lambda: status_error(409, "conflict_error"), id="409"),
    pytest.param(lambda: status_error(429, "rate_limit_error"), id="429"),
    pytest.param(lambda: status_error(500, "api_error"), id="500"),
    pytest.param(lambda: status_error(529, "overloaded_error"), id="529"),
    # An error after the stream's 200 arrives as an SSE error event (errors page, F210).
    pytest.param(lambda: status_error(200, "overloaded_error"), id="mid-stream"),
]


@pytest.mark.parametrize("error", RETRYABLE)
def test_transient_failures_are_retried_twice_then_the_provider_is_unavailable(
    error: Any,  # Any: a factory of SDK exceptions
) -> None:
    claude, sdk, sleeps = make([error(), error(), error()])

    with pytest.raises(ProviderUnavailable):
        claude.create(REQUEST)

    assert len(sdk.messages.calls) == 3
    assert sleeps == [0.5, 1.0]


def test_a_transient_failure_then_a_reply_returns_the_reply() -> None:
    claude, sdk, sleeps = make([status_error(500, "api_error"), message()])

    reply = claude.create(REQUEST)

    assert reply["stop_reason"] == "tool_use" and len(sdk.messages.calls) == 2
    assert sleeps == [0.5]


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(status_error(400, "invalid_request_error", WORKSPACE_LIMIT), id="workspace"),
        pytest.param(
            status_error(400, "invalid_request_error", ORGANISATION_LIMIT), id="organisation"
        ),
        pytest.param(body_error(429, TIER_CAP_BODY), id="tier-cap"),
    ],
)
def test_a_spend_limit_stops_at_once_without_a_retry(error: anthropic.APIStatusError) -> None:
    claude, sdk, sleeps = make([error, message()])

    with pytest.raises(SpendLimitReached):
        claude.create(REQUEST)

    assert len(sdk.messages.calls) == 1 and sleeps == []


@pytest.mark.parametrize(
    ("status", "kind"),
    [(400, "invalid_request_error"), (401, "authentication_error"), (402, "billing_error")],
)
def test_any_other_client_error_is_rejected_unretried(status: int, kind: str) -> None:
    error = status_error(status, kind, "tools.0: bad schema")
    claude, sdk, sleeps = make([error, message()])

    with pytest.raises(ProviderRejected, match=f"http_{status}") as raised:
        claude.create(REQUEST)

    assert raised.value.__cause__ is error and len(sdk.messages.calls) == 1 and sleeps == []
    assert "tools.0: bad schema" in str(raised.value)  # the provider's words say what to fix


def test_a_long_provider_message_is_cut_to_the_configured_length() -> None:
    claude, _, _ = make([status_error(400, "invalid_request_error", "x" * (MESSAGE_MAX * 3))])

    with pytest.raises(ProviderRejected) as raised:
        claude.create(REQUEST)

    assert str(raised.value).count("x") == MESSAGE_MAX


def test_the_backoff_doubles_up_to_its_cap() -> None:
    sdk, sleeps = _Sdk([connection_error()] * 5 + [message()]), list[float]()
    policy = client.RetryPolicy(retries=5, initial_s=0.5, max_s=3.0)

    client.ClaudeClient(sdk, policy, MESSAGE_MAX, sleep=sleeps.append).create(REQUEST)

    assert sleeps == [0.5, 1.0, 2.0, 3.0, 3.0]


def test_the_request_reaches_the_sdk_unchanged() -> None:
    claude, sdk, _ = make([message()])

    claude.create(REQUEST)

    assert sdk.messages.calls == [REQUEST]


def test_the_reply_is_plain_json_with_its_request_id_and_no_empty_fields() -> None:
    claude, _, _ = make([message()])

    reply = claude.create(REQUEST)

    assert reply["request_id"] == "req_123"
    assert reply["content"][0] == {"type": "text", "text": "Looking."}
    assert reply["content"][1]["input"] == {"sheet_id": "s1"}
    assert reply["usage"]["cache_creation_input_tokens"] == 3000


def test_count_tokens_sends_only_the_counted_fields_and_returns_the_number() -> None:
    counted = anthropic.types.MessageTokensCount(input_tokens=4321)
    claude, sdk, _ = make([status_error(503, "api_error"), counted])
    fields = {k: REQUEST[k] for k in ("model", "system", "messages", "tools")}

    assert claude.count_tokens(fields) == 4321
    assert sdk.messages.calls == [fields, fields]


def test_each_attempt_is_logged_once_with_its_latency(caplog: pytest.LogCaptureFixture) -> None:
    claude, _, _ = make([status_error(500, "api_error"), message()])

    with caplog.at_level(logging.INFO, logger=client.log.name):
        claude.create(REQUEST)

    lines = [r for r in caplog.records if getattr(r, "event", None) == "claude_create"]
    assert [getattr(r, "outcome", None) for r in lines] == ["retry", "tool_use"]
    assert all(isinstance(getattr(r, "latency_ms", None), int) for r in lines)


def test_connect_turns_the_sdk_retries_off_and_sets_the_timeouts() -> None:
    cfg, editor = config.load_claude(), config.load().limits.editor

    claude = client.connect(SecretStr("test-anthropic-key"), cfg, editor)

    sdk = claude.sdk
    assert isinstance(sdk, anthropic.Anthropic)
    assert sdk.max_retries == 0 and editor.transient_retries == 2  # D45, EDITOR §3
    assert sdk.timeout == anthropic.Timeout(cfg.timeout_s, connect=cfg.connect_timeout_s)
    assert claude.policy == client.RetryPolicy(2, cfg.retry_initial_s, cfg.retry_max_s)
    assert claude.message_max == cfg.error_message_max_chars


STREAM_EVENTS: list[dict[str, Any]] = [  # Any: server-sent event JSON
    {
        "type": "message_start",
        "message": {
            "id": "msg_s",
            "type": "message",
            "role": "assistant",
            "model": "claude-haiku-5-5",
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {
                "input_tokens": 12,
                "output_tokens": 1,
                "cache_creation_input_tokens": 3000,
                "cache_read_input_tokens": 0,
            },
        },
    },
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hi"}},
    {"type": "content_block_stop", "index": 0},
    {
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
        "usage": {"output_tokens": 7},
    },
    {"type": "message_stop"},
]


def test_create_streams_so_the_sdk_never_refuses_the_long_retry() -> None:
    """The real SDK refuses a non-streaming request whose max_tokens could outlast ten minutes
    (anthropic 1.13.0 _calculate_nonstreaming_timeout): max_tokens_retry must still go out."""
    sent: list[dict[str, Any]] = []  # Any: request body JSON

    def answer(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        events = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in STREAM_EVENTS)
        headers = {"content-type": "text/event-stream", "request-id": "req_s"}
        return httpx2.Response(200, headers=headers, content=events.encode())

    editor = config.load().limits.editor
    sdk = anthropic.Anthropic(
        api_key="test-anthropic-key",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(answer)),
    )

    reply = client.ClaudeClient(sdk, POLICY, MESSAGE_MAX).create(
        {**REQUEST, "max_tokens": editor.max_tokens_retry}
    )

    assert sent[0]["stream"] is True and sent[0]["max_tokens"] == editor.max_tokens_retry
    assert sent[0]["cache_control"] == {"type": "ephemeral"}
    assert sent[0]["output_config"] == {"effort": "high"}
    assert reply["content"] == [{"type": "text", "text": "Hi"}]
    assert reply["stop_reason"] == "end_turn" and reply["request_id"] == "req_s"
    assert reply["usage"]["cache_creation_input_tokens"] == 3000
    assert reply["usage"]["output_tokens"] == 7


class _DropAfterFirstEvent(httpx2.SyncByteStream):
    """A stream whose connection drops after message_start (peer closed mid-body)."""

    def __iter__(self) -> Iterator[bytes]:
        first = STREAM_EVENTS[0]
        yield f"event: {first['type']}\ndata: {json.dumps(first)}\n\n".encode()
        raise httpx2.RemoteProtocolError("peer closed connection without sending complete body")


def _streaming_sdk(answer: Callable[[httpx2.Request], httpx2.Response]) -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key="test-anthropic-key",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(answer)),
    )


def test_a_connection_dropped_mid_stream_is_retried_then_unavailable() -> None:
    calls: list[int] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        headers = {"content-type": "text/event-stream"}
        return httpx2.Response(200, headers=headers, stream=_DropAfterFirstEvent())

    sleeps = list[float]()
    claude = client.ClaudeClient(_streaming_sdk(answer), POLICY, MESSAGE_MAX, sleep=sleeps.append)

    with pytest.raises(ProviderUnavailable):
        claude.create(REQUEST)

    assert len(calls) == 3 and sleeps == [0.5, 1.0]


def test_a_stream_that_ends_before_message_stop_is_retried() -> None:
    cut = STREAM_EVENTS[:3]  # message_start and a text delta, then a clean end of body
    calls: list[int] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        events = cut if len(calls) == 1 else STREAM_EVENTS
        body = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
        headers = {"content-type": "text/event-stream"}
        return httpx2.Response(200, headers=headers, content=body.encode())

    sleeps = list[float]()
    reply = client.ClaudeClient(
        _streaming_sdk(answer), POLICY, MESSAGE_MAX, sleep=sleeps.append
    ).create(REQUEST)

    assert reply["stop_reason"] == "end_turn" and len(calls) == 2 and sleeps == [0.5]


def test_a_refusal_without_an_anthropic_body_keeps_the_sdks_text() -> None:
    """A proxy's HTML 403 has no error.type or message; the SDK's own text still says what broke."""

    def answer(request: httpx2.Request) -> httpx2.Response:
        headers = {"content-type": "text/html"}
        return httpx2.Response(403, headers=headers, content=b"<html>blocked by the proxy</html>")

    claude = client.ClaudeClient(_streaming_sdk(answer), POLICY, MESSAGE_MAX)

    with pytest.raises(ProviderRejected) as raised:
        claude.create(REQUEST)

    assert "http_403 unknown" in str(raised.value) and "blocked by the proxy" in str(raised.value)
