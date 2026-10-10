"""The Claude adapter (docs/EDITOR.md §3, D45): our retries, the spend-limit stop, plain JSON out.

The SDK object is a fake that raises the SDK's own exception classes, built on httpx2 requests
and responses (doc ledger: anthropic, httpx2), so no request leaves the process.
"""

import logging
from collections.abc import Sequence
from typing import Any

import anthropic
import httpx2
import pytest
from pydantic import SecretStr

from reel_studio.adapters.claude import client
from reel_studio.core import config
from reel_studio.core.errors import ProviderUnavailable, SpendLimitReached

URL = "https://api.anthropic.test/v1/messages"
WORKSPACE_LIMIT = (
    "You have reached your specified workspace API usage limits. "
    "You will regain access on 2026-11-01 at 00:00 UTC."
)
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


def status_error(status: int, kind: str, message: str = "boom") -> anthropic.APIStatusError:
    request = httpx2.Request("POST", URL)
    body = {"type": "error", "error": {"type": kind, "message": message}}
    response = httpx2.Response(status, json=body, request=request, headers={"request-id": "r1"})
    return anthropic.APIStatusError(message, response=response, body=body)


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

    def create(self, **kwargs: Any) -> Any:  # Any: SDK keyword arguments
        return self._next(kwargs)

    def count_tokens(self, **kwargs: Any) -> Any:  # Any: SDK keyword arguments
        return self._next(kwargs)


class _Sdk:
    def __init__(self, script: Sequence[object]) -> None:
        self.messages = _Messages(script)


def make(script: Sequence[object]) -> tuple[client.ClaudeClient, _Sdk, list[float]]:
    sdk, sleeps = _Sdk(script), list[float]()
    return client.ClaudeClient(sdk, POLICY, sleep=sleeps.append), sdk, sleeps


RETRYABLE = [
    pytest.param(connection_error, id="connection"),
    pytest.param(timeout_error, id="timeout"),
    pytest.param(lambda: status_error(408, "timeout_error"), id="408"),
    pytest.param(lambda: status_error(409, "conflict_error"), id="409"),
    pytest.param(lambda: status_error(429, "rate_limit_error"), id="429"),
    pytest.param(lambda: status_error(500, "api_error"), id="500"),
    pytest.param(lambda: status_error(529, "overloaded_error"), id="529"),
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
        pytest.param(status_error(429, "enforced_spend_limit_reached"), id="organisation"),
    ],
)
def test_a_spend_limit_stops_at_once_without_a_retry(error: anthropic.APIStatusError) -> None:
    claude, sdk, sleeps = make([error, message()])

    with pytest.raises(SpendLimitReached):
        claude.create(REQUEST)

    assert len(sdk.messages.calls) == 1 and sleeps == []


def test_any_other_client_error_propagates_unretried() -> None:
    error = status_error(400, "invalid_request_error", "tools.0: bad schema")
    claude, sdk, sleeps = make([error, message()])

    with pytest.raises(anthropic.APIStatusError) as raised:
        claude.create(REQUEST)

    assert raised.value is error and len(sdk.messages.calls) == 1 and sleeps == []


def test_the_backoff_doubles_up_to_its_cap() -> None:
    sdk, sleeps = _Sdk([connection_error()] * 5 + [message()]), list[float]()
    policy = client.RetryPolicy(retries=5, initial_s=0.5, max_s=3.0)

    client.ClaudeClient(sdk, policy, sleep=sleeps.append).create(REQUEST)

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
