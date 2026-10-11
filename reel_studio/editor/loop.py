"""The editor loop, written by hand (D30, docs/EDITOR.md §3): tools until write_edl is accepted.

Every request carries the same system prompt, tools, tool_choice and output settings, so the
prefix is cached (D34, F18). Each call is guarded by the meter on its worst case (D37), costed,
and written as one line to requests.jsonl (EDITOR §9).
"""

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reel_studio.core import constants, ports
from reel_studio.core.config import Editor
from reel_studio.core.errors import ModelRefusal, OutputTooLong
from reel_studio.core.logging import get_logger
from reel_studio.editor.media.edl_models import Edl
from reel_studio.editor.meter import Meter, Usage
from reel_studio.editor.tools import Toolbox

type Message = dict[str, Any]  # Any: an Anthropic message as plain JSON

log = get_logger(__name__)

STAGE = "planning"
NUDGE = "Call write_edl with the finished edit list."  # EDITOR §3


@dataclass(frozen=True)
class Session:
    claude: ports.Claude
    meter: Meter
    clock: ports.Clock
    log: Path  # requests.jsonl
    editor: Editor
    call: str = "editor"  # editor | critic, the requests.jsonl `call` field


@dataclass
class Outcome:
    edl: Edl | None
    warnings: list[str]
    turns: int
    messages: list[Message] = field(default_factory=list)


def _cached(usage: Mapping[str, Any], key: str) -> int:  # Any: usage JSON
    value = usage.get(key)  # the cache fields may be absent or null when nothing was cached
    return int(value) if value is not None else 0


def usage_of(reply: Mapping[str, Any]) -> Usage:  # Any: response JSON
    """A reply without input or output counts is an error, never a free call."""
    u = reply["usage"]
    return Usage(
        input_tokens=int(u["input_tokens"]),
        output_tokens=int(u["output_tokens"]),
        cache_write=_cached(u, "cache_creation_input_tokens"),
        cache_read=_cached(u, "cache_read_input_tokens"),
    )


def call_claude(session: Session, request: Message, turn: int) -> Message:
    """Guard, call, cost and record one request (EDITOR §8, §9)."""
    model = str(request["model"])
    counted: dict[str, Any] = {
        k: request[k] for k in ("model", "system", "messages", "tools") if k in request
    }
    session.meter.guard(model, session.claude.count_tokens(counted), int(request["max_tokens"]))
    started = time.monotonic()
    reply: Message = {**session.claude.create(request)}
    latency_ms = round((time.monotonic() - started) * constants.MS_PER_S)
    usage = usage_of(reply)
    cost = session.meter.add(model, usage)
    tools_used = [b["name"] for b in reply.get("content", []) if b.get("type") == "tool_use"]
    line = {
        "ts": session.clock.now().isoformat(),
        "call": session.call,
        "model": model,
        "turn": turn,
        "input_tokens": usage.input_tokens,
        "cache_write": usage.cache_write,
        "cache_read": usage.cache_read,
        "output_tokens": usage.output_tokens,
        "cost_usd": str(cost),
        "spent_usd": str(session.meter.spent),
        "stop_reason": reply.get("stop_reason"),
        "latency_ms": latency_ms,
        "tools": tools_used,
        "request_id": reply.get("request_id"),
    }
    with session.log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line) + "\n")
    log.info(
        "%s turn %d: %s",
        session.call,
        turn,
        reply.get("stop_reason"),
        extra={
            "stage": STAGE,
            "event": session.call,
            "latency_ms": latency_ms,
            "outcome": reply.get("stop_reason"),
        },
    )
    return reply


def _request(
    session: Session, system: str, tools: list[Message], messages: list[Message], max_tokens: int
) -> Message:
    editor = session.editor
    return {
        "model": editor.model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        "tools": tools,
        "tool_choice": {"type": "auto"},
        "cache_control": {"type": "ephemeral"},  # D34, F07
        "output_config": {"effort": editor.effort},  # D33
    }


def _reply(
    session: Session, system: str, tools: list[Message], messages: list[Message], turn: int
) -> Message:
    """One turn's response; a cut-off reply is dropped and retried once with more room."""
    editor = session.editor
    reply = call_claude(
        session, _request(session, system, tools, messages, editor.max_tokens), turn
    )
    if reply.get("stop_reason") != "max_tokens":
        return reply
    # The cut turn may hold a tool_use with no result, which the API rejects: never send it back.
    reply = call_claude(
        session, _request(session, system, tools, messages, editor.max_tokens_retry), turn
    )
    if reply.get("stop_reason") == "max_tokens":
        raise OutputTooLong(f"reply cut off twice at turn {turn}")
    return reply


def continue_with(history: list[Message], text: str) -> list[Message]:
    """Add `text` as the next user turn. When the last message is the user's (tool results, or
    a brief whose empty reply was dropped) it joins that message, behind its blocks (F12), so
    roles keep alternating; every earlier message stays byte-equal (D34)."""
    if not history or history[-1]["role"] != "user":
        return [*history, {"role": "user", "content": text}]
    content = history[-1]["content"]
    blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
    return [*history[:-1], {"role": "user", "content": [*blocks, {"type": "text", "text": text}]}]


def answer(history: list[Message], reply: Mapping[str, Any]) -> list[Message]:  # Any: JSON
    """The assistant turn goes back as it came, except an empty one: the API takes no empty
    assistant content, and an empty end_turn is answered with a new user message instead."""
    content = reply.get("content", [])
    return [*history, {"role": "assistant", "content": content}] if content else list(history)


def run(
    session: Session, box: Toolbox, system: str, opening: str, history: list[Message] | None = None
) -> Outcome:
    """Run until write_edl is accepted. `history` continues an earlier conversation (critic, F2)."""
    tools = box.definitions()
    messages = continue_with(history if history is not None else [], opening)
    box.accepted = None
    for turn in range(1, session.editor.max_turns + 1):
        reply = _reply(session, system, tools, messages, turn)
        messages = answer(messages, reply)
        stop = reply.get("stop_reason")
        if stop == "tool_use":
            uses = [b for b in reply.get("content", []) if b.get("type") == "tool_use"]
            results = []
            for block in uses:  # every result, in one user message, before any text (F12)
                result = box.run(str(block["name"]), block.get("input"))
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": result.content,
                        "is_error": result.is_error,
                    }
                )
            messages.append({"role": "user", "content": results})
            if box.accepted is not None:
                return Outcome(box.accepted, box.warnings, turn, messages)
        elif stop == "end_turn":
            messages = continue_with(messages, NUDGE)
        else:  # refusal, or a stop reason this loop does not handle
            raise ModelRefusal(f"model stopped with {stop}")
    raise ModelRefusal(f"no edit list after {session.editor.max_turns} turns")
