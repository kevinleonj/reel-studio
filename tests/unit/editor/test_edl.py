"""The edit list: kit schema plus the v1 fields (docs/EDITOR.md §7); every violation reported."""

from typing import Any

import pytest

from reel_studio.core import config
from reel_studio.editor.media import edl
from reel_studio.editor.media.edl_models import Edl
from reel_studio.editor.media.measure import Window
from reel_studio.editor.media.shots import Clip, Shots


def _clip(cid: str, duration: float, fps: int, kind: str = "video") -> Clip:
    return Clip(
        id=cid,
        source=f"{cid}.mov",
        proxy=f"clips/{cid}.mp4",
        duration=duration,
        orientation="portrait",
        proxy_w=1080,
        proxy_h=1920,
        proxy_fps=fps,
        color="sdr",
        kind=kind,
        color_stats=None,
        median_sharpness=100.0,
    )


def _window(wid: str, cid: str, start: float, end: float) -> Window:
    return Window(
        id=wid,
        clip=cid,
        start=start,
        end=end,
        motion=10.0,
        sharpness=100.0,
        luma=120.0,
        colourful=40.0,
        warmth=10.0,
    )


SHOTS = Shots(
    name="t",
    clips=[_clip("c01", 10.0, 30), _clip("c02", 5.0, 60), _clip("c03", 3.0, 30, "photo")],
    windows=[
        _window("w001", "c01", 0.0, 5.0),
        _window("w002", "c01", 5.0, 10.0),
        _window("w003", "c02", 0.0, 5.0),
    ],
    sheets=[],
    total_raw_seconds=18.0,
)


def _edl(**top: Any) -> dict[str, Any]:  # Any: raw JSON as Claude or a person writes it
    segments = [
        {"clip": "c01", "in": 0.5, "out": 2.5, "role": "hook"},
        {"clip": "c02", "in": 0.0, "out": 1.0, "speed": 0.5, "role": "reveal", "text": "Slow"},
        {"clip": "c01", "in": 6.0, "out": 9.0, "speed": 2.0, "role": "mix"},
        {"clip": "c03", "in": 0.0, "out": 1.5, "role": "payoff"},
    ]
    raw: dict[str, Any] = {
        "format": "recipe",
        "versions": [{"name": "A", "hook_text": "Crackly tops", "segments": segments}],
        "audio": {"natural_db": 0},
    }
    raw.update(top)
    return raw


def _check(raw: dict[str, Any]) -> edl.Report:
    return edl.validate(raw, SHOTS, config.load_media())


def test_valid_edl_has_no_errors() -> None:
    report = _check(_edl())

    assert report.errors == []


def test_check_returns_every_violation_not_the_first() -> None:
    raw = _edl()
    segs = raw["versions"][0]["segments"]
    segs[0]["clip"] = "c99"
    segs[1]["speed"] = 9.0
    segs[2]["text"] = "x" * 50

    report = _check(raw)

    assert len(report.errors) == 3, report.errors
    assert any("unknown clip id" in e for e in report.errors)
    assert any("speed 9.0 outside" in e for e in report.errors)
    assert any("label over 42 characters" in e for e in report.errors)


def test_music_is_refused() -> None:
    report = _check(_edl(audio={"natural_db": 0, "music": "song.mp3"}))

    assert any("music is not supported" in e for e in report.errors)


def test_slow_motion_on_a_30_fps_clip_is_an_error() -> None:
    raw = _edl()
    raw["versions"][0]["segments"][2]["speed"] = 0.5

    report = _check(raw)

    assert any("stutters" in e for e in report.errors)


def test_exactly_one_version() -> None:
    raw = _edl()
    raw["versions"].append({**raw["versions"][0], "name": "B"})

    assert any("need exactly 1 version" in e for e in _check(raw).errors)


def test_title_is_read_as_hook_text() -> None:
    raw = _edl()
    version = raw["versions"][0]
    version["title"] = version.pop("hook_text")

    parsed = edl.parse(raw)

    assert isinstance(parsed, Edl)
    assert parsed.versions[0].hook_text == "Crackly tops"


def test_unknown_field_is_a_listed_error_not_a_crash() -> None:
    report = _check(_edl(soundtrack="jazz"))

    assert any("soundtrack" in e for e in report.errors)


def test_v1_caption_and_music_hint_lengths() -> None:
    media = config.load_media()
    raw = _edl(
        caption="c" * (media.edl.caption_max_chars + 1),
        music_hint="m" * (media.edl.music_hint_max_chars + 1),
    )

    errors = _check(raw).errors

    assert any("caption" in e for e in errors)
    assert any("music_hint" in e for e in errors)


def test_v1_fields_are_accepted() -> None:
    raw = _edl(
        style="recipe",
        dropped=[{"clip": "c02", "reason": "same shot as c01"}],
        preferences=[{"text": "keep it short", "applied": True, "why": "30 s cut"}],
        caption="Crackly tops in 20 minutes",
        music_hint="upbeat, 110 bpm",
        assumptions=["30 s default"],
        check_by_eye=["c03 focus"],
    )
    raw["versions"][0]["segments"][0].update(
        beat="promise the payoff", quote=None, visual_check=False
    )

    assert _check(raw).errors == []


def test_dropped_clip_must_exist() -> None:
    report = _check(_edl(dropped=[{"clip": "c42", "reason": "blurred"}]))

    assert any("dropped" in e and "c42" in e for e in report.errors)


def test_order_style_must_match() -> None:
    report = edl.validate(_edl(style="recipe"), SHOTS, config.load_media(), order_style="talking")

    assert any("style" in e for e in report.errors)


def test_craft_warnings_do_not_block() -> None:
    raw = _edl()
    raw["versions"][0]["segments"][0]["role"] = "process"  # first shot is not a hook

    report = _check(raw)

    assert report.errors == []
    assert any("first segment role is not hook" in w for w in report.warnings)


@pytest.mark.parametrize(
    "bad", [{"fit": "stretch"}, {"rotate": 90}, {"zoom": 3.0}, {"focus_x": 1.5}]
)
def test_framing_fields_are_range_checked(bad: dict[str, Any]) -> None:
    raw = _edl()
    raw["versions"][0]["segments"][2].update(bad)

    assert len(_check(raw).errors) == 1


def test_zero_speed_on_the_first_segment_is_an_error_not_a_crash() -> None:
    raw = _edl()
    raw["versions"][0]["segments"][0]["speed"] = 0

    report = _check(raw)

    assert any("speed 0" in e for e in report.errors)


@pytest.mark.parametrize("field", ["text_position", "title_position"])
def test_unknown_text_position_is_an_error(field: str) -> None:
    raw = _edl()
    if field == "text_position":
        raw["versions"][0]["segments"][1]["text_position"] = "bottom"
    else:
        raw["versions"][0]["title_position"] = "bottom"

    assert any("bottom" in e or field in e for e in _check(raw).errors)


@pytest.mark.parametrize("where", ["label", "hook"])
def test_blank_text_is_an_error(where: str) -> None:
    raw = _edl()
    if where == "label":
        raw["versions"][0]["segments"][1]["text"] = "   "
    else:
        raw["versions"][0]["hook_text"] = "  "

    assert any("blank" in e for e in _check(raw).errors)


def test_music_false_is_allowed_as_in_the_kit() -> None:
    assert _check(_edl(audio={"natural_db": 0, "music": False})).errors == []


def test_v1_edl_must_drop_every_unused_clip() -> None:
    raw = _edl(style="recipe", dropped=[])
    raw["versions"][0]["segments"] = [
        s for s in raw["versions"][0]["segments"] if s["clip"] != "c02"
    ]

    errors = _check(raw).errors

    assert any("c02" in e and "dropped" in e for e in errors)


def test_jump_cut_warns_when_one_side_omits_the_default_speed() -> None:
    raw = _edl()
    raw["versions"][0]["segments"] = [
        {"clip": "c01", "in": 0.5, "out": 2.5, "role": "hook"},
        {"clip": "c01", "in": 3.0, "out": 4.5, "speed": 1.0, "role": "mix"},
        {"clip": "c03", "in": 0.0, "out": 1.5, "role": "payoff"},
    ]

    assert any("jump cut" in w for w in _check(raw).warnings)


@pytest.mark.parametrize(
    ("change", "warning"),
    [
        ({"hook_text": "one two three four five six seven eight"}, "words"),
        ({"last_role": "mix"}, "weak ending"),
        ({"hook_out": 4.5}, "hook lasts"),
    ],
)
def test_craft_warnings(change: dict[str, Any], warning: str) -> None:
    raw = _edl()
    version = raw["versions"][0]
    if "hook_text" in change:
        version["hook_text"] = change["hook_text"]
    if "last_role" in change:
        version["segments"][-1]["role"] = change["last_role"]
    if "hook_out" in change:
        version["segments"][0]["out"] = change["hook_out"]

    assert any(warning in w for w in _check(raw).warnings)


def test_shape_only_check_needs_no_clips() -> None:
    errors = edl.precheck({"versions": [], "audio": {"music": "x"}}, config.load_media())

    assert any("music" in e for e in errors)
    assert any("need exactly 1 version" in e for e in errors)
