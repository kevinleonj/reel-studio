"""From an input folder to shots.json: prepare, measure, sheets (kit prep.py:225-302 main).

The folder is only read (D02). Everything written goes under `work`: proxies in clips/, contact
sheets and their legend in sheets/, and shots.json.
"""

from pathlib import Path

from reel_studio.core.config import Sheets
from reel_studio.core.logging import get_logger
from reel_studio.core.media_config import Media
from reel_studio.editor.media import measure, prepare, sheets
from reel_studio.editor.media.shots import SHOTS, Clip, Shots
from reel_studio.editor.media.tools import Ffmpeg

log = get_logger(__name__)

SHEETS = "sheets"


def build_shots(folder: Path, work: Path, ffmpeg: Ffmpeg, media: Media, limits: Sheets) -> Shots:
    """Prepare every usable file, measure it, draw the sheets, write work/shots.json."""
    proxies = prepare.prepare_folder(folder, work, ffmpeg, media)
    clips: list[Clip] = []
    windows: list[measure.Window] = []
    scenes: list[tuple[prepare.Proxy, list[tuple[float, float]]]] = []
    for proxy in proxies:
        result = measure.measure_clip(work, proxy, media)
        clips.append(Clip.of(proxy, result.color_stats, result.median_sharpness))
        for window in result.windows:
            windows.append(window.model_copy(update={"id": f"w{len(windows) + 1:03d}"}))
        scenes.append((proxy, result.cuts))
    paths, _ = sheets.build(work, scenes, work / SHEETS, limits, media)
    shots = Shots(
        name=folder.name,
        clips=clips,
        windows=windows,
        sheets=[str(p.relative_to(work)) for p in paths],
        total_raw_seconds=round(sum(c.duration for c in clips), 1),
    )
    (work / SHOTS).write_text(shots.model_dump_json(indent=1), encoding="utf-8")
    log.info(
        "%d clips, %d windows, %d sheets",
        len(clips),
        len(windows),
        len(paths),
        extra={"stage": prepare.STAGE, "event": "shots", "outcome": "ok"},
    )
    return shots


def load_shots(work: Path) -> Shots:
    return Shots.model_validate_json((work / SHOTS).read_text(encoding="utf-8"))
