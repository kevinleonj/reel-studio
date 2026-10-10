"""The five editor tools (EDITOR.md §4): strict schemas, guards that teach, images ≤ 2000 px."""

import base64
import io
import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from reel_studio.core import config
from reel_studio.editor import tools
from reel_studio.editor.media.measure import Window
from reel_studio.editor.media.shots import Clip, Shots

UNSUPPORTED = {
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "maxItems",
    "default",
}  # F208


def _clip(cid: str, duration: float) -> Clip:
    return Clip(
        id=cid,
        source=f"{cid}.mov",
        proxy=f"clips/{cid}.mp4",
        duration=duration,
        orientation="portrait",
        proxy_w=1080,
        proxy_h=1920,
        proxy_fps=30,
        color="sdr",
        kind="video",
        color_stats=None,
        median_sharpness=100.0,
    )


def _jpeg(path: Path, size: tuple[int, int]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (90, 60, 30)).save(path)
    return path


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tools.Toolbox:
    _jpeg(tmp_path / "sheets" / "sheet01.jpg", (1536, 864))
    legend = [
        {"sheet": 1, "tile": 1, "clip": "c01", "t": 2.0},
        {"sheet": 1, "tile": 2, "clip": "c02", "t": 1.0},
    ]
    (tmp_path / "sheets" / "legend.json").write_text(json.dumps(legend), encoding="utf-8")
    window = Window(
        id="w001",
        clip="c01",
        start=0.0,
        end=4.0,
        motion=5.0,
        sharpness=100.0,
        luma=120.0,
        colourful=30.0,
        warmth=8.0,
    )
    shots = Shots(
        name="t",
        clips=[_clip("c01", 10.0), _clip("c02", 5.0)],
        windows=[window],
        sheets=["sheets/sheet01.jpg"],
        total_raw_seconds=15.0,
    )
    big = _jpeg(tmp_path / "big.jpg", (3000, 1000))
    monkeypatch.setattr(tools, "_render_strip", lambda *_: big)
    monkeypatch.setattr(tools, "_render_preview", lambda *_: Image.open(big))
    ctx = tools.Context(
        work=tmp_path,
        input_dir=None,
        shots=shots,
        media=config.load_media(),
        limits=config.load().limits,
        order_style=None,
        voice=False,
    )
    return tools.Toolbox(ctx)


def _images(content: list[dict[str, Any]]) -> list[Image.Image]:  # Any: content blocks
    return [
        Image.open(io.BytesIO(base64.b64decode(b["source"]["data"])))
        for b in content
        if b["type"] == "image"
    ]


def _walk(node: Any) -> list[dict[str, Any]]:  # Any: JSON Schema
    found = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found += _walk(value)
    elif isinstance(node, list):
        for value in node:
            found += _walk(value)
    return found


def test_five_strict_tools_without_unsupported_keywords(box: tools.Toolbox) -> None:
    defs = box.definitions()

    assert [d["name"] for d in defs] == [
        "read_sheet",
        "read_strip",
        "read_grade_preview",
        "read_transcript",
        "write_edl",
    ]
    for d in defs:
        assert d["strict"] is True
        nodes = _walk(d["input_schema"])
        assert not [n for n in nodes if UNSUPPORTED & set(n)]
        objects = [n for n in nodes if n.get("type") == "object"]
        assert objects and all(n.get("additionalProperties") is False for n in objects)


def test_definitions_are_identical_across_builds(box: tools.Toolbox) -> None:
    assert json.dumps(box.definitions()) == json.dumps(box.definitions())


def test_unknown_sheet_names_the_valid_ids(box: tools.Toolbox) -> None:
    result = box.run("read_sheet", {"sheet_id": "sheet09"})

    assert result.is_error and "sheet01" in result.text()


def test_sheet_comes_with_its_legend(box: tools.Toolbox) -> None:
    result = box.run("read_sheet", {"sheet_id": "sheet01"})

    assert not result.is_error
    assert "tile 2: c02 at 1.0s" in result.text()
    assert len(_images(result.content)) == 1


def test_images_are_shrunk_to_2000_px(box: tools.Toolbox) -> None:
    result = box.run("read_strip", {"clip": "c01", "start_s": 0.0, "end_s": 4.0})

    (image,) = _images(result.content)
    assert max(image.size) <= config.load().limits.sheets.max_image_side_px


@pytest.mark.parametrize(
    ("args", "words"),
    [
        ({"clip": "c09", "start_s": 0, "end_s": 1}, "c01, c02"),
        ({"clip": "c01", "start_s": 3, "end_s": 2}, "0 <="),
        ({"clip": "c01", "start_s": 0, "end_s": 7}, "at most 6"),
        ({"clip": "c02", "start_s": 4, "end_s": 6}, "5.00"),
    ],
)
def test_strip_guards_name_the_valid_values(
    box: tools.Toolbox, args: dict[str, Any], words: str
) -> None:
    result = box.run("read_strip", args)

    assert result.is_error and words in result.text()


def test_the_13th_strip_is_refused(box: tools.Toolbox) -> None:
    for _ in range(config.load().limits.editor.max_strips):
        assert not box.run("read_strip", {"clip": "c01", "start_s": 0, "end_s": 1}).is_error

    result = box.run("read_strip", {"clip": "c01", "start_s": 0, "end_s": 1})

    assert result.is_error and "12" in result.text()


def test_the_third_grade_preview_is_refused(box: tools.Toolbox) -> None:
    assert not box.run("read_grade_preview", {"frames": None}).is_error
    assert not box.run("read_grade_preview", {"frames": ["c01:2.0"]}).is_error

    assert box.run("read_grade_preview", {"frames": None}).is_error


def test_bad_frame_reference_is_an_error(box: tools.Toolbox) -> None:
    result = box.run("read_grade_preview", {"frames": ["c01-2.0"]})

    assert result.is_error and "clip:time" in result.text()


def test_no_transcript_when_voice_is_off(box: tools.Toolbox) -> None:
    result = box.run("read_transcript", {"clip": "c01"})

    assert result.is_error and "no transcript for this order" in result.text()


def test_write_edl_reports_every_violation(box: tools.Toolbox) -> None:
    edl = {
        "versions": [
            {
                "name": "A",
                "segments": [
                    {"clip": "c09", "in": 0, "out": 1},
                    {"clip": "c01", "in": 0, "out": 1, "speed": 20},
                ],
            }
        ]
    }

    result = box.run("write_edl", edl)

    assert result.is_error
    assert "unknown clip id" in result.text() and "speed 20" in result.text()
    assert box.accepted is None


def test_write_edl_accepts_a_valid_list_with_warnings(box: tools.Toolbox) -> None:
    edl = {
        "versions": [
            {
                "name": "A",
                "segments": [
                    {"clip": "c01", "in": 0, "out": 2, "role": "hook"},
                    {"clip": "c02", "in": 0, "out": 2, "role": "payoff"},
                ],
            }
        ]
    }

    result = box.run("write_edl", edl)

    assert not result.is_error and "accepted" in result.text()
    assert box.accepted is not None


def test_bad_input_shape_and_unknown_tools_do_not_raise(box: tools.Toolbox) -> None:
    shape = box.run("read_strip", {"clip": "c01"})
    unknown = box.run("delete_files", {})

    assert shape.is_error and "end_s" in shape.text()
    assert unknown.is_error and "read_sheet" in unknown.text()
