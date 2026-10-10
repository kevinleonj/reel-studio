"""A scripted Claude: returns recorded responses in order and keeps every request it received."""

import copy
from collections.abc import Mapping, Sequence
from typing import Any

type Record = dict[str, Any]  # Any: an Anthropic message or request, as plain JSON

NO_USAGE = {
    "input_tokens": 10,
    "output_tokens": 5,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
}


def text(words: str) -> Record:
    return {"type": "text", "text": words}


def tool_use(block_id: str, name: str, args: Mapping[str, Any]) -> Record:  # Any: tool input
    return {"type": "tool_use", "id": block_id, "name": name, "input": dict(args)}


def response(
    content: Sequence[Record], stop_reason: str, usage: Mapping[str, int] | None = None
) -> Record:
    return {
        "id": "msg",
        "type": "message",
        "role": "assistant",
        "content": list(content),
        "stop_reason": stop_reason,
        "usage": dict(usage if usage is not None else NO_USAGE),
        "request_id": "req_fake",
    }


class FakeClaude:
    """Implements the Claude port. `script` items are responses or exceptions to raise."""

    def __init__(self, script: Sequence[Record | Exception], prompt_tokens: int = 1_000) -> None:
        self.script = list(script)
        self.prompt_tokens = prompt_tokens
        self.requests: list[Record] = []
        self.counted: list[Record] = []

    def count_tokens(self, request: Mapping[str, Any]) -> int:  # Any: request JSON
        self.counted.append(copy.deepcopy(dict(request)))
        return self.prompt_tokens

    def create(self, request: Mapping[str, Any]) -> Record:  # Any: request JSON
        self.requests.append(copy.deepcopy(dict(request)))
        if not self.script:
            raise AssertionError("FakeClaude ran out of scripted responses")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return copy.deepcopy(item)
