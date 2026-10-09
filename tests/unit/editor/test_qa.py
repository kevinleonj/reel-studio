"""QA's pure parts: audio measurements parsed from ffmpeg's stderr, hard checks are booleans."""

from pathlib import Path

import numpy as np
from PIL import Image

from reel_studio.core import config
from reel_studio.editor.media import qa, qa_sheets

EBUR_STDERR = """
[Parsed_ebur128_0 @ 0x1] t: 1.0 TARGET:-23 LUFS M: -20.1 S: -21.0 I: -20.0 LUFS
[blackdetect @ 0x2] black_start:0.5 black_end:0.8 black_duration:0.3
[freezedetect @ 0x3] lavfi.freezedetect.freeze_start: 2.25
  Integrated loudness:
    I:         -14.2 LUFS
"""


class _Stderr:
    def measure(self, args: list[str], what: str) -> str:
        return EBUR_STDERR


def test_audio_measurement_reads_the_last_integrated_loudness() -> None:
    result = qa.measure_audio(_Stderr(), Path("x.mp4"), config.load_media().qa)  # type: ignore[arg-type]

    assert result.lufs == -14.2
    assert result.black == [(0.5, 0.8)]
    assert result.freeze == [2.25]


def test_hard_checks_are_booleans_and_text_free_reel_is_safe() -> None:
    checks = qa.HardChecks(
        spec_text=True,
        spec_clean=True,
        size_duration_text=True,
        size_duration_clean=True,
        no_black_frames=True,
        text_in_safe_zone=qa.all_inside([]),
    )

    dumped = checks.model_dump()

    assert set(dumped) == {
        "spec_text",
        "spec_clean",
        "size_duration_text",
        "size_duration_clean",
        "no_black_frames",
        "text_in_safe_zone",
    }
    assert all(isinstance(v, bool) for v in dumped.values())
    assert dumped["text_in_safe_zone"] is True


def test_grid_is_capped_at_the_image_limit(tmp_path: Path) -> None:
    media = config.load_media()
    tile = Image.fromarray(np.zeros((338, 190, 3), dtype=np.uint8))
    items = [(f"{i}", tile) for i in range(80)]  # a long Reel: 40 cuts, two tiles each
    out = tmp_path / "cuts.jpg"
    limit = config.load().limits.sheets.max_image_side_px

    qa_sheets.grid(items, qa_sheets.Layout(8, (190, 338), safe=False), out, media, limit)

    with Image.open(out) as image:
        assert max(image.size) <= limit
