"""Synthetic iPhone-like clips for tests and the STEP-02 gate; no binaries live in git.

Port of the kit's selftest inputs (selftest.py:25-51): portrait HEVC 10-bit HLG with rotation
metadata (iPhone HDR), a 60 fps clip with audio, a landscape clip without audio, a long take with
a hard cut (90 s here, STEP-02 task 1; the kit's was 14 s), a still photo, and a style photo
whose name marks it as a colour reference, not footage (kit grade.py:33).

    uv run python tests/fixtures/make_clips.py <empty folder>
"""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

HDR = "IMG_0001.MOV"
SIXTY_FPS = "IMG_0002.MOV"
LANDSCAPE = "IMG_0003.MOV"
LONG_TAKE = "IMG_0004.MOV"
PHOTO = "IMG_0005.jpeg"
STYLE_PHOTO = "IMG_0006_VSCO.jpg"
NAMES = (HDR, SIXTY_FPS, LANDSCAPE, LONG_TAKE, PHOTO, STYLE_PHOTO)

LONG_TAKE_S = 90  # STEP-02 task 1
CUT_AT_S = LONG_TAKE_S // 2  # the hard cut: testsrc, then smptehdbars
CAPTURED_AT = 1_767_261_600  # 2026-01-01 10:00 UTC: the fixture "capture" time, in epoch seconds
ENCODE_TIMEOUT_S = 600
FILTERS_TIMEOUT_S = 30
# Fixture encodes only: speed over quality, the product's encoder settings live in media.toml.
FAST = ("-preset", "ultrafast")

# Where ffmpeg with zscale lives: Homebrew's keg-only ffmpeg-full on a Mac (F45), else PATH
# (Debian and Ubuntu build ffmpeg with libzimg).
KEG = Path("/opt/homebrew/opt/ffmpeg-full/bin")


@dataclass(frozen=True)
class Tools:
    ffmpeg: Path
    ffprobe: Path


def _has_zscale(ffmpeg: Path) -> bool:
    done = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [str(ffmpeg), "-hide_banner", "-filters"],
        capture_output=True,
        text=True,
        check=False,
        timeout=FILTERS_TIMEOUT_S,
    )
    return any(line.split()[1:2] == ["zscale"] for line in done.stdout.splitlines() if line.strip())


def find_tools() -> Tools:
    """The first ffmpeg/ffprobe pair whose ffmpeg has zscale; fail loudly if there is none."""
    candidates = [KEG]
    on_path = shutil.which("ffmpeg")
    if on_path is not None:
        candidates.append(Path(on_path).parent)
    for folder in candidates:
        ffmpeg, ffprobe = folder / "ffmpeg", folder / "ffprobe"
        if ffmpeg.exists() and ffprobe.exists() and _has_zscale(ffmpeg):
            return Tools(ffmpeg, ffprobe)
    raise RuntimeError(f"no ffmpeg with zscale in {[str(c) for c in candidates]}")


def _run(tools: Tools, *args: str) -> None:
    subprocess.run(  # noqa: S603 - fixed argv, no shell
        [str(tools.ffmpeg), "-y", "-v", "error", *args],
        check=True,
        timeout=ENCODE_TIMEOUT_S,
    )


def make(folder: Path, tools: Tools) -> list[Path]:
    """Write the six files into `folder` (must exist) and return their paths."""
    tmp = folder / "hdr_tmp.mov"
    # selftest.py:30-37: 10-bit HLG BT.2020 HEVC, then rotation metadata on a stream copy
    _run(
        tools,
        "-f",
        "lavfi",
        "-i",
        "testsrc2=s=1920x1080:r=30:d=4",
        "-f",
        "lavfi",
        "-i",
        "sine=f=440:d=4",
        "-vf",
        "zscale=tin=bt709:pin=bt709:min=bt709:t=arib-std-b67:p=bt2020:m=bt2020nc,"
        "format=yuv420p10le",
        "-c:v",
        "libx265",
        "-x265-params",
        "log-level=error",
        *FAST,
        "-tag:v",
        "hvc1",
        "-color_primaries",
        "bt2020",
        "-color_trc",
        "arib-std-b67",
        "-colorspace",
        "bt2020nc",
        "-c:a",
        "aac",
        str(tmp),
    )
    _run(tools, "-display_rotation:v:0", "90", "-i", str(tmp), "-c", "copy", str(folder / HDR))
    tmp.unlink()
    # selftest.py:41-42
    _run(
        tools,
        "-f",
        "lavfi",
        "-i",
        "testsrc2=s=1080x1920:r=60",
        "-f",
        "lavfi",
        "-i",
        "sine=f=660",
        "-t",
        "5",
        "-c:v",
        "libx264",
        *FAST,
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(folder / SIXTY_FPS),
    )
    # selftest.py:43-44
    _run(
        tools,
        "-f",
        "lavfi",
        "-i",
        "testsrc2=s=1920x1080:r=30",
        "-t",
        "4",
        "-c:v",
        "libx264",
        *FAST,
        "-pix_fmt",
        "yuv420p",
        str(folder / LANDSCAPE),
    )
    # selftest.py:45-48, lengthened to LONG_TAKE_S
    _run(
        tools,
        "-f",
        "lavfi",
        "-i",
        f"testsrc=s=1080x1920:r=30:d={CUT_AT_S}",
        "-f",
        "lavfi",
        "-i",
        f"smptehdbars=s=1080x1920:r=30:d={LONG_TAKE_S - CUT_AT_S}",
        "-f",
        "lavfi",
        "-i",
        f"sine=f=330:d={LONG_TAKE_S}",
        "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1:a=0[v]",
        "-map",
        "[v]",
        "-map",
        "2:a",
        "-c:v",
        "libx264",
        *FAST,
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(folder / LONG_TAKE),
    )
    # selftest.py:49-50
    Image.new("RGB", (1200, 1600), (200, 120, 60)).save(folder / PHOTO)
    Image.new("RGB", (800, 1000), (150, 90, 70)).save(folder / STYLE_PHOTO)
    # These files carry no capture time, so prepare orders them by file time; fix it one second
    # apart in NAMES order so the clip ids (c01 = HDR ... c05 = photo) never depend on encode speed.
    for offset, name in enumerate(NAMES):
        stamp = CAPTURED_AT + offset
        (folder / name).touch()
        os.utime(folder / name, (stamp, stamp))
    return [folder / name for name in NAMES]


def make_sdr_twin(dst: Path, tools: Tools) -> Path:
    """The HDR clip's test pattern encoded SDR BT.709, same rotation: the luma reference
    Kevin chose on 9 Oct 2026 for the tonemap test (docs/handoff/engine.md)."""
    tmp = dst.with_name("sdr_tmp.mov")
    _run(
        tools,
        "-f",
        "lavfi",
        "-i",
        "testsrc2=s=1920x1080:r=30:d=4",
        "-f",
        "lavfi",
        "-i",
        "sine=f=440:d=4",
        "-c:v",
        "libx264",
        *FAST,
        "-pix_fmt",
        "yuv420p",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-colorspace",
        "bt709",
        "-c:a",
        "aac",
        str(tmp),
    )
    _run(tools, "-display_rotation:v:0", "90", "-i", str(tmp), "-c", "copy", str(dst))
    tmp.unlink()
    return dst


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        sys.stderr.write("usage: make_clips.py <folder>\n")
        return 2
    folder = Path(argv[0])
    folder.mkdir(parents=True, exist_ok=True)
    for path in make(folder, find_tools()):
        sys.stdout.write(f"{path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
