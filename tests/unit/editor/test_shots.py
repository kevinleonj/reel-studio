"""The clip and window table the editor reads (kit shots.py)."""

from reel_studio.editor.media.measure import Window
from reel_studio.editor.media.shots import Clip, Shots, format_table


def _clip(cid: str) -> Clip:
    return Clip(
        id=cid,
        source=f"{cid}_a_very_long_source_file_name.mov",
        proxy=f"clips/{cid}.mp4",
        duration=4.0,
        orientation="portrait",
        proxy_w=1080,
        proxy_h=1920,
        proxy_fps=30,
        color="sdr",
        kind="video",
        color_stats=None,
        median_sharpness=200.0,
    )


def test_table_lists_every_clip_and_window_with_relative_sharpness() -> None:
    window = Window(
        id="w001",
        clip="c01",
        start=0.0,
        end=2.0,
        motion=3.0,
        sharpness=100.0,
        luma=120.0,
        colourful=30.0,
        warmth=8.0,
    )
    shots = Shots(
        name="cookies",
        clips=[_clip("c01"), _clip("c02")],
        windows=[window],
        sheets=["sheets/sheet01.jpg"],
        total_raw_seconds=8.0,
    )

    table = format_table(shots)

    assert "cookies: 2 clips, 8.0s raw" in table
    assert "c01_a_very_long_source_f " in table  # source cut to 24 characters
    assert " 0.50 " in table  # 100 / clip median 200
    assert table.endswith("sheets: sheets/sheet01.jpg")


def test_empty_order_still_formats() -> None:
    shots = Shots(name="empty", clips=[], windows=[], sheets=[], total_raw_seconds=0.0)

    assert format_table(shots).startswith("empty: 0 clips")
