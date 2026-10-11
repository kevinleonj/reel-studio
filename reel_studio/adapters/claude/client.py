"""The Claude port over the anthropic SDK (docs/EDITOR.md §3, D45; doc ledger: anthropic).

The SDK's own retries are off (`max_retries=0`, F15); this wrapper owns them, so a spend limit is
never retried and every attempt is logged once with its latency. Requests and replies cross the
port as plain JSON: the loop never sees an SDK type. `create` streams: the SDK refuses a plain
request whose max_tokens could take over ten minutes, which max_tokens_retry does (F210).
"""

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

import anthropic
import httpx2
from pydantic import SecretStr

from reel_studio.core import constants
from reel_studio.core.config import ClaudeClient as ClientConfig
from reel_studio.core.config import Editor
from reel_studio.core.errors import ProviderRejected, ProviderUnavailable, SpendLimitReached
from reel_studio.core.logging import get_logger

type Record = dict[str, Any]  # Any: a request or reply as plain JSON

log = get_logger(__name__)

STAGE = "planning"
# F13: how a spend limit answers. A limit Kevin set is a 400 told apart from any other bad request
# only by the start of its message (organisation or workspace); the tier cap is a 429 whose
# error.details.error_code tells it apart from a rate limit.
SPEND_LIMIT_PREFIXES = (
    "You have reached your specified API usage limits",
    "You have reached your specified workspace API usage limits",
)
SPEND_LIMIT_CODE = "enforced_spend_limit_reached"
# F15: the statuses the SDK itself would retry; 5xx are added in _transient.
RETRY_STATUSES = frozenset(
    {HTTPStatus.REQUEST_TIMEOUT, HTTPStatus.CONFLICT, HTTPStatus.TOO_MANY_REQUESTS}
)
# An error inside a stream comes after its 200, so only error.type tells what it was (F210);
# these are the types of the retried statuses (errors page).
RETRY_TYPES = frozenset({"rate_limit_error", "api_error", "timeout_error", "overloaded_error"})


@dataclass(frozen=True)
class RetryPolicy:
    retries: int  # attempts after the first
    initial_s: float
    max_s: float

    def delay(self, attempt: int) -> float:
        """Seconds to wait after failed attempt `attempt` (0-based): doubling, capped."""
        return float(min(self.initial_s * 2**attempt, self.max_s))


def _error_field(error: anthropic.APIStatusError, *path: str) -> object:
    """body["error"][path...], or None when the body has no such field."""
    value: object = error.body
    for key in ("error", *path):
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _is_spend_limit(error: anthropic.APIStatusError) -> bool:
    if error.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        return _error_field(error, "details", "error_code") == SPEND_LIMIT_CODE
    message = _error_field(error, "message")
    return (
        error.status_code == HTTPStatus.BAD_REQUEST
        and isinstance(message, str)
        and message.startswith(SPEND_LIMIT_PREFIXES)
    )


def _transient(error: anthropic.APIError) -> bool:
    if isinstance(error, anthropic.APIConnectionError):  # includes APITimeoutError
        return True
    if isinstance(error, anthropic.APIStatusError):
        return (
            error.status_code in RETRY_STATUSES
            or error.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR
            or error.type in RETRY_TYPES
        )
    return False


def _outcome(error: anthropic.APIError) -> str:
    if isinstance(error, anthropic.APIStatusError):
        return f"http_{error.status_code}"
    return type(error).__name__


class ClaudeClient:
    """Implements `ports.Claude`."""

    def __init__(
        self,
        sdk: Any,  # Any: anthropic.Anthropic, or a test double with its two messages methods
        policy: RetryPolicy,
        message_max: int,  # chars of a refused request's message kept
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.sdk = sdk
        self.policy = policy
        self.message_max = message_max
        self._sleep = sleep

    def _call(
        self, name: str, send: Callable[[], Any], outcome: Callable[[Any], str]
    ) -> Any:  # Any: the SDK's reply
        for attempt in range(self.policy.retries + 1):
            started = time.monotonic()
            try:
                reply = send()
            except anthropic.APIError as error:
                latency_ms = round((time.monotonic() - started) * constants.MS_PER_S)
                self._failed(name, error, attempt, latency_ms)
                continue
            latency_ms = round((time.monotonic() - started) * constants.MS_PER_S)
            log.info(
                "%s ok after %d ms",
                name,
                latency_ms,
                extra={
                    "stage": STAGE,
                    "event": name,
                    "latency_ms": latency_ms,
                    "outcome": outcome(reply),
                },
            )
            return reply
        raise ProviderUnavailable(f"{name}: no answer after {self.policy.retries + 1} attempts")

    def _failed(self, name: str, error: anthropic.APIError, attempt: int, latency_ms: int) -> None:
        """Log the failed attempt; raise unless it is transient and retries remain."""
        status = error if isinstance(error, anthropic.APIStatusError) else None
        spend = status is not None and _is_spend_limit(status)
        retry = not spend and _transient(error) and attempt < self.policy.retries
        log.warning(
            "%s failed: %s (request %s)",
            name,
            _outcome(error),
            status.request_id if status is not None else None,
            extra={
                "stage": STAGE,
                "event": name,
                "latency_ms": latency_ms,
                "outcome": "retry" if retry else _outcome(error),
            },
        )
        if spend:
            raise SpendLimitReached(f"{name}: {_outcome(error)} spend limit (F13)") from error
        if retry:
            self._sleep(self.policy.delay(attempt))
            return
        if _transient(error):
            raise ProviderUnavailable(f"{name}: {_outcome(error)} after retries") from error
        # bad key, billing, bad request; a proxy's or WAF's body has no Anthropic error shape
        kind = status.type if status is not None and status.type is not None else "unknown"
        field = _error_field(status, "message") if status is not None else None
        said = field if isinstance(field, str) and field.strip() else error.message
        words = str(said)[: self.message_max]
        raise ProviderRejected(f"{name}: {_outcome(error)} {kind}: {words}") from error

    def count_tokens(self, request: Mapping[str, Any]) -> int:  # Any: request JSON
        counted = self._call(
            "claude_count", lambda: self.sdk.messages.count_tokens(**request), lambda _: "ok"
        )
        return int(counted.input_tokens)

    def create(self, request: Mapping[str, Any]) -> Record:  # Any: request JSON
        def send() -> tuple[Any, str | None]:  # Any: anthropic.types.Message
            try:
                with self.sdk.messages.stream(**request) as stream:
                    message = stream.get_final_message()
            except httpx2.TransportError as exc:  # the SDK wraps only the connection setup (F210)
                raise anthropic.APIConnectionError(request=exc.request) from exc
            if message.stop_reason is None:  # the body ended before message_stop: a cut stream
                raise anthropic.APIConnectionError(
                    message="stream ended before message_stop", request=stream.response.request
                )
            return message, stream.request_id

        reply, request_id = self._call("claude_create", send, lambda sent: str(sent[0].stop_reason))
        # exclude_none: the reply's content goes back in the next request, so no null fields
        record: Record = reply.model_dump(mode="json", exclude_none=True)
        record["request_id"] = request_id
        return record


def connect(api_key: SecretStr, cfg: ClientConfig, editor: Editor) -> ClaudeClient:
    """The real client: SDK retries off (limits.toml, D45), our timeouts (anthropic.toml, F207)."""
    sdk = anthropic.Anthropic(
        api_key=api_key.get_secret_value(),
        max_retries=editor.sdk_max_retries,
        timeout=anthropic.Timeout(cfg.timeout_s, connect=cfg.connect_timeout_s),
    )
    policy = RetryPolicy(editor.transient_retries, cfg.retry_initial_s, cfg.retry_max_s)
    return ClaudeClient(sdk, policy, message_max=cfg.error_message_max_chars)
