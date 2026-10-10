"""ffmpeg and ffprobe: run, probe, check a filter (port of kit common.py:92-151).

Paths come from EditorSettings (absolute, no PATH lookup). Every call is logged once as a JSON
line with its latency and outcome (D74); a failure raises RenderError carrying the last lines of
stderr, the way the kit's KitError did.
"""

import json
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reel_studio.core import constants
from reel_studio.core.errors import RenderError
from reel_studio.core.logging import get_logger
from reel_studio.core.media_config import Tools

log = get_logger(__name__)

STAGE = "media"


@dataclass(frozen=True)
class Probe:
    """What the editor needs to know about one clip; width and height are as displayed."""

    width: int
    height: int
    fps: float
    duration: float
    codec: str | None
    pix_fmt: str | None
    color_transfer: str | None
    color_primaries: str | None
    color_space: str | None
    has_audio: bool
    creation_time: str | None


def _rate(value: object) -> float:
    """ffprobe "30000/1001" -> 29.97; "0/0" or nothing -> 0 (kit common.py:118-122)."""
    if not isinstance(value, str) or value in {"", "0/0"}:
        return 0.0
    num, _, den = value.partition("/")
    return float(num) / float(den if den else 1)


def _rotation(video: Mapping[str, Any]) -> int:  # Any: ffprobe JSON
    rotation = 0
    for side in video.get("side_data_list") or []:
        if "rotation" in side:
            rotation = round(float(side["rotation"]))
    tags = video.get("tags") or {}
    if "rotate" in tags:
        rotation = int(tags["rotate"])
    return rotation


def parse_probe(data: Mapping[str, Any], name: str) -> Probe:  # Any: ffprobe JSON
    """ffprobe `-show_streams -show_format` JSON -> Probe (kit common.py:112-147)."""
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise RenderError(f"{name} has no video stream")
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    if width <= 0 or height <= 0:  # a later division by the size would stop the whole order
        raise RenderError(f"{name} has no picture size ({width}x{height})")
    if abs(_rotation(video)) % constants.HALF_TURN_DEG == constants.QUARTER_TURN_DEG:
        width, height = height, width
    fmt = data.get("format") or {}
    duration = video.get("duration")
    duration = duration if duration is not None else fmt.get("duration")
    tags = {**(fmt.get("tags") or {}), **(video.get("tags") or {})}
    created = tags.get("com.apple.quicktime.creationdate")
    fps = _rate(video.get("avg_frame_rate"))
    return Probe(
        width=width,
        height=height,
        fps=fps if fps > 0 else _rate(video.get("r_frame_rate")),
        duration=float(duration) if duration is not None else 0.0,
        codec=video.get("codec_name"),
        pix_fmt=video.get("pix_fmt"),
        color_transfer=video.get("color_transfer"),
        color_primaries=video.get("color_primaries"),
        color_space=video.get("color_space"),
        has_audio=audio is not None,
        creation_time=created if created is not None else tags.get("creation_time"),
    )


def is_hdr(info: Probe) -> bool:
    return info.color_transfer in constants.HDR_TRANSFERS


class Ffmpeg:
    """The one door to ffmpeg and ffprobe."""

    def __init__(self, ffmpeg: Path, ffprobe: Path, cfg: Tools) -> None:
        self.ffmpeg, self.ffprobe, self.cfg = ffmpeg, ffprobe, cfg

    def _call(
        self, argv: Sequence[str], what: str, timeout_s: int
    ) -> subprocess.CompletedProcess[str]:
        tool = Path(argv[0]).name
        started = time.monotonic()
        outcome = "error"
        try:
            done = subprocess.run(  # noqa: S603 - argv built by this package, no shell
                list(argv), capture_output=True, text=True, check=False, timeout=timeout_s
            )
            outcome = "ok" if done.returncode == 0 else f"exit {done.returncode}"
            return done
        except subprocess.TimeoutExpired as exc:
            outcome = "timeout"
            raise RenderError(f"{what} timed out after {timeout_s} s") from exc
        except OSError as exc:  # missing or not executable: FFMPEG_PATH/FFPROBE_PATH are wrong
            outcome = "cannot_start"
            raise RenderError(f"{what}: cannot start {argv[0]} ({exc.strerror})") from exc
        finally:
            latency_ms = round((time.monotonic() - started) * constants.MS_PER_S)
            extra = {
                "stage": STAGE,
                "event": "ffmpeg",
                "latency_ms": latency_ms,
                "outcome": outcome,
            }
            log.info("%s: %s", tool, what, extra=extra)

    def run(self, args: Sequence[str], what: str) -> str:
        """`ffmpeg <args>`; returns stderr (loudnorm prints its JSON there)."""
        done = self._call([str(self.ffmpeg), *args], what, self.cfg.run_timeout_s)
        if done.returncode != 0:
            tail = "\n".join(done.stderr.strip().splitlines()[-self.cfg.error_tail_lines :])
            raise RenderError(f"{what} failed (exit {done.returncode}).\n{tail}")
        return done.stderr

    def measure(self, args: Sequence[str], what: str) -> str:
        """`ffmpeg <args>` run for the measurements it prints; stderr even on a non-zero exit."""
        return self._call([str(self.ffmpeg), *args], what, self.cfg.run_timeout_s).stderr

    def probe(self, path: Path) -> Probe:
        argv = [
            str(self.ffprobe),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ]
        done = self._call(argv, f"probe {path.name}", self.cfg.probe_timeout_s)
        if done.returncode != 0:
            detail = done.stderr.strip()[: self.cfg.probe_error_chars]
            raise RenderError(f"Cannot read {path.name}: {detail}")
        return parse_probe(json.loads(done.stdout), path.name)

    def check(self) -> None:
        """Both binaries start, before any file is judged: a broken install is a deployment
        fault, and must never read as the customer's files being unusable."""
        for tool in (self.ffmpeg, self.ffprobe):
            done = self._call(
                [str(tool), "-version"], f"check {tool.name}", self.cfg.probe_timeout_s
            )
            if done.returncode != 0:
                raise RenderError(f"{tool} -version exited {done.returncode}")

    def has_filter(self, name: str) -> bool:
        argv = [str(self.ffmpeg), "-hide_banner", "-filters"]
        done = self._call(argv, "list filters", self.cfg.probe_timeout_s)
        return any(line.split()[1:2] == [name] for line in done.stdout.splitlines() if line.strip())
