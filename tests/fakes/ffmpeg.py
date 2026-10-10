"""A stand-in for tools.Ffmpeg: no binary, records calls, lets a test look in the work folder."""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from reel_studio.core.errors import RenderError
from reel_studio.editor.media.tools import Probe, parse_probe

PORTRAIT = Probe(1080, 1920, 30.0, 4.0, "h264", "yuv420p", "bt709", None, None, True, None)


class FakeFfmpeg:
    """`run` writes an empty file at the output path (the last argument) after `on_run` looks."""

    def __init__(
        self,
        probes: dict[str, Probe] | None = None,
        unreadable: set[str] | None = None,
        on_run: Callable[[Sequence[str]], None] | None = None,
        raw: dict[str, dict[str, Any]] | None = None,  # Any: ffprobe JSON, parsed for real
    ) -> None:
        self.probes = probes if probes is not None else {}
        self.raw = raw if raw is not None else {}
        self.unreadable = unreadable if unreadable is not None else set()
        self.on_run = on_run
        self.calls: list[Sequence[str]] = []

    def run(self, args: Sequence[str], what: str) -> str:
        self.calls.append(args)
        if self.on_run is not None:
            self.on_run(args)
        Path(args[-1]).write_bytes(b"")
        return ""

    def measure(self, args: Sequence[str], what: str) -> str:
        self.calls.append(args)
        return ""

    def probe(self, path: Path) -> Probe:
        if path.name in self.unreadable:
            raise RenderError(f"Cannot read {path.name}")
        if path.name in self.raw:
            return parse_probe(self.raw[path.name], path.name)
        return self.probes.get(path.name, PORTRAIT)

    def check(self) -> None:
        return None

    def has_filter(self, name: str) -> bool:
        return True
