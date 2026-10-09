"""Normalise raw clips and photos into SDR H.264 proxies (port of kit prep.py:37-115, 225-275).

Each original is copied into the work folder, proxied and then deleted there before the next
one starts (STEP-02 task 2), so a 40-clip order never holds every original twice on disk. The
input folder itself is only read (D02). A file that cannot be read is skipped and logged; only
an order with nothing usable fails (NoUsableInput, docs/EDITOR.md §10).
"""

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import pillow_heif
from PIL import Image, ImageOps, UnidentifiedImageError

from reel_studio.core import constants
from reel_studio.core.errors import MediaError, NoUsableInput
from reel_studio.core.logging import get_logger
from reel_studio.core.media_config import Media, Photo, Tonemap
from reel_studio.editor.media.tools import Ffmpeg, Probe, is_hdr

log = get_logger(__name__)

ORIGINALS = "originals"  # work-folder staging for one original at a time
CLIPS = "clips"  # proxies, cNN.mp4
STAGE = "prepare"

pillow_heif.register_heif_opener()  # iPhone photos are often HEIC (kit prep.py:94-96)


@dataclass(frozen=True)
class Context:
    """What every proxy step needs: the ffmpeg door, the tunables, and whether zscale exists."""

    ffmpeg: Ffmpeg
    media: Media
    zscale: bool


@dataclass(frozen=True)
class Proxy:
    """One normalised clip; `path` is relative to the work folder."""

    id: str
    source: str
    path: str
    duration: float
    width: int
    height: int
    fps: int
    color: str
    kind: Literal["video", "photo"]

    @property
    def orientation(self) -> Literal["portrait", "landscape"]:
        return "portrait" if self.height >= self.width else "landscape"


def footage(folder: Path, reference_words: tuple[str, ...]) -> list[Path]:
    """Video and photo files, without briefs, hidden files or style photos (kit prep.py:239-242)."""
    files = []
    for path in folder.iterdir():
        suffix, stem = path.suffix.lower(), path.stem.lower()
        if (
            not path.is_file()
            or path.name.startswith(".")
            or path.name.lower() in constants.SKIP_NAMES
        ):
            continue
        if suffix not in constants.VIDEO_EXT | constants.IMAGE_EXT:
            continue
        if suffix in constants.IMAGE_EXT and any(word in stem for word in reference_words):
            # Substring match as in the kit; say so, since "refried.jpg" matches too (Needs Kevin).
            log.info(
                "style photo, not footage: %s",
                path.name,
                extra={"stage": STAGE, "event": "style_photo"},
            )
            continue
        files.append(path)
    return files


def sort_key(path: Path, info: Probe | None) -> tuple[float, str]:
    """Capture time first, then file time, then name (kit prep.py:50-58)."""
    stamp = None
    if info is not None and info.creation_time is not None:
        try:
            stamp = datetime.fromisoformat(info.creation_time.replace("Z", "+00:00")).timestamp()
        except ValueError:
            log.info("unreadable creation time on %s", path.name, extra={"stage": STAGE})
    return (stamp if stamp is not None else path.stat().st_mtime, path.name)


def cover_size(width: int, height: int) -> tuple[int, int]:
    """Smallest even size that covers the Reel frame (kit prep.py:61-63)."""
    scale = max(constants.OUT_W / width, constants.OUT_H / height)
    return round(width * scale / 2) * 2, round(height * scale / 2) * 2


def tonemap_chain(transfer: str, cfg: Tonemap) -> str:
    """HDR (HLG or PQ, BT.2020) -> SDR BT.709 with zscale (kit prep.py:37-47)."""
    return (
        f"zscale=tin={transfer}:pin=bt2020:min=bt2020nc:t=linear:npl={cfg.npl},format=gbrpf32le,"
        f"zscale=p=bt709,tonemap=tonemap={cfg.algorithm}:desat={cfg.desat},"
        "zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
    )


def _silent_track() -> list[str]:
    return ["-f", "lavfi", "-i", f"anullsrc=r={constants.AUDIO_RATE_HZ}:cl=stereo"]


def make_proxy(src: Path, dst: Path, info: Probe, ctx: Context) -> tuple[int, int, int, str]:
    """Video -> proxy; returns width, height, fps and a colour note (kit prep.py:66-87)."""
    cfg = ctx.media.prepare
    width, height = cover_size(info.width, info.height)
    fps = cfg.proxy_fps_high if info.fps >= cfg.high_fps_threshold else cfg.proxy_fps_low
    filters, note = [], "sdr"
    if is_hdr(info) and info.color_transfer is not None:
        if ctx.zscale:
            filters.append(tonemap_chain(info.color_transfer, cfg.tonemap))
            note = "hdr->sdr"
        else:
            note = "HDR NOT TONEMAPPED: this ffmpeg has no zscale"
            log.warning("%s: %s", src.name, note, extra={"stage": STAGE, "event": "no_zscale"})
    filters += [
        f"scale={width}:{height}:flags={cfg.scale_flags}",
        f"fps={fps}",
        "format=yuv420p",
        "setsar=1",
    ]
    args = ["-y", "-v", "error", "-i", str(src)]
    if not info.has_audio:
        args += _silent_track()
    args += [
        "-map",
        "0:v:0",
        "-map",
        "0:a:0" if info.has_audio else "1:a:0",
        "-vf",
        ",".join(filters),
        "-c:v",
        cfg.video_codec,
        "-crf",
        str(cfg.crf),
        "-preset",
        cfg.preset,
        "-g",
        str(fps * cfg.gop_seconds),
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-colorspace",
        "bt709",
        "-c:a",
        cfg.audio_codec,
        "-b:a",
        f"{cfg.audio_bitrate_kbps}k",
        "-ar",
        str(constants.AUDIO_RATE_HZ),
        "-ac",
        str(constants.AUDIO_CHANNELS),
        "-shortest",
        "-movflags",
        "+faststart",
        str(dst),
    ]
    ctx.ffmpeg.run(args, f"Normalising {src.name}")
    return width, height, fps, note


def photo_proxy(src: Path, dst: Path, ffmpeg: Ffmpeg, cfg: Photo) -> tuple[int, int, int]:
    """Still -> short clip with a slow push-in so it does not look frozen (prep.py:90-115)."""
    try:
        with Image.open(src) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise MediaError(f"Cannot open photo {src.name}: {exc}") from exc
    width, height = cover_size(*image.size)
    still = dst.with_suffix(".png")
    image.resize((width, height), Image.Resampling.LANCZOS).save(still)
    frames = int(cfg.seconds * cfg.fps)
    zoom = (
        f"[0:v]scale={width * cfg.supersample}:{height * cfg.supersample},"
        f"zoompan=z='1+{cfg.push_in}*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d=1:s={width}x{height}:fps={cfg.fps},format=yuv420p,setsar=1[v]"
    )
    args = [
        "-y",
        "-v",
        "error",
        "-loop",
        "1",
        "-framerate",
        str(cfg.fps),
        "-t",
        str(cfg.seconds),
        "-i",
        str(still),
        *_silent_track(),
        "-filter_complex",
        zoom,
        "-map",
        "[v]",
        "-map",
        "1:a",
        "-t",
        str(cfg.seconds),
        "-c:v",
        "libx264",
        "-crf",
        str(cfg.crf),
        "-preset",
        cfg.preset,
        "-g",
        str(cfg.gop_frames),
        "-c:a",
        "aac",
        "-ar",
        str(constants.AUDIO_RATE_HZ),
        "-ac",
        str(constants.AUDIO_CHANNELS),
        str(dst),
    ]
    try:
        ffmpeg.run(args, f"Animating photo {src.name}")
    finally:
        still.unlink(missing_ok=True)
    return width, height, cfg.fps


def _one(src: Path, cid: str, work: Path, info: Probe | None, ctx: Context) -> Proxy:
    staged = work / ORIGINALS / src.name
    shutil.copyfile(src, staged)
    dst = work / CLIPS / f"{cid}.mp4"
    try:
        if info is not None:
            width, height, fps, note = make_proxy(staged, dst, info, ctx)
            kind: Literal["video", "photo"] = "video"
        else:
            width, height, fps = photo_proxy(staged, dst, ctx.ffmpeg, ctx.media.prepare.photo)
            note, kind = "photo", "photo"
    finally:
        staged.unlink(missing_ok=True)
    duration = round(ctx.ffmpeg.probe(dst).duration, constants.SECONDS_DECIMALS)
    return Proxy(cid, src.name, f"{CLIPS}/{dst.name}", duration, width, height, fps, note, kind)


def prepare_folder(folder: Path, work: Path, ffmpeg: Ffmpeg, media: Media) -> list[Proxy]:
    """Every usable file in `folder` -> proxies in `work/clips`, in capture order."""
    (work / ORIGINALS).mkdir(parents=True, exist_ok=True)
    (work / CLIPS).mkdir(parents=True, exist_ok=True)
    files = footage(folder, media.grade.reference_words)
    found = len(files)
    probes: dict[Path, Probe] = {}
    for path in files:
        if path.suffix.lower() in constants.VIDEO_EXT:
            try:
                probes[path] = ffmpeg.probe(path)
            except MediaError as exc:
                log.warning(
                    "SKIPPED %s: %s", path.name, exc, extra={"stage": STAGE, "event": "skip"}
                )
    files = [p for p in files if p in probes or p.suffix.lower() in constants.IMAGE_EXT]
    files.sort(key=lambda p: sort_key(p, probes.get(p)))
    ctx = Context(ffmpeg, media, ffmpeg.has_filter("zscale"))
    proxies: list[Proxy] = []
    for src in files:
        cid = f"c{len(proxies) + 1:02d}"
        try:
            proxy = _one(src, cid, work, probes.get(src), ctx)
        except MediaError as exc:  # one bad file must not stop the Reel (kit prep.py:264-266)
            log.warning("SKIPPED %s: %s", src.name, exc, extra={"stage": STAGE, "event": "skip"})
            continue
        log.info(
            "%s <- %s %.1fs %dfps %s",
            cid,
            src.name,
            proxy.duration,
            proxy.fps,
            proxy.color,
            extra={"stage": STAGE, "event": "proxy", "outcome": "ok"},
        )
        proxies.append(proxy)
    if not proxies:
        raise NoUsableInput(f"no usable video or photo in {found} file(s)")
    return proxies
