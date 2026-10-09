"""On-screen text as transparent 1080x1920 PNGs (kit textcards.py)."""

from pathlib import Path

import pytest
from PIL import Image

from reel_studio.core import config, constants
from reel_studio.editor.media import textcards

LONGEST = "Brown the butter until it smells nutty now"  # 42 characters, the label maximum


@pytest.mark.parametrize("style", sorted(textcards.STYLES))
@pytest.mark.parametrize("position", ["top", "center", "low"])
def test_longest_label_stays_inside_the_safe_zone(
    style: str, position: str, tmp_path: Path
) -> None:
    assert len(LONGEST) == config.load_media().edl.label_max_chars
    out = tmp_path / "card.png"

    box = textcards.render_card(
        textcards.Card(LONGEST, "step", position), out, style, config.load_media()
    )

    assert box.inside_safe_zone
    assert box.lines <= config.load_media().text.max_lines
    with Image.open(out) as image:
        assert image.size == (constants.OUT_W, constants.OUT_H)
        assert image.mode == "RGBA"


def test_a_long_title_shrinks_its_font(tmp_path: Path) -> None:
    text = "The crackly top trick that every single baker should know about today"

    box = textcards.render_card(
        textcards.Card(text, "title", "top"), tmp_path / "t.png", "outline", config.load_media()
    )

    assert box.font_px < config.load_media().text.title_px


def test_unknown_position_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown text position"):
        textcards.render_card(
            textcards.Card("Hi", "step", "side"), tmp_path / "x.png", "outline", config.load_media()
        )


def test_unknown_kind_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown text kind"):
        textcards.render_card(
            textcards.Card("Hi", "caption", "top"),
            tmp_path / "x.png",
            "outline",
            config.load_media(),
        )
