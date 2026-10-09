"""On-screen text as transparent 1080x1920 PNGs, no libass or drawtext (port of kit textcards.py).

Styles: outline (white text, thin dark outline and a soft shadow, no box; reads on any food),
box (white text on a translucent dark rounded box), plain (white text only, for calm dark
backgrounds). The text shrinks until it fits the safe zone in at most `max_lines` lines.
"""

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from reel_studio.core import constants
from reel_studio.core.media_config import Media, Text
from reel_studio.editor.media.fonts import bold

STYLES = frozenset({"outline", "box", "plain"})  # kit textcards.py:17
POSITIONS = frozenset({"top", "center", "low"})  # kit textcards.py:57-64
KINDS = frozenset({"title", "step"})  # kit textcards.py:16


@dataclass(frozen=True)
class Card:
    text: str
    kind: str  # title (the hook) or step (a segment label)
    position: str


@dataclass(frozen=True)
class TextBox:
    """Where the text landed, in output pixels (qa.py checks the safe zone)."""

    x0: int
    y0: int
    x1: int
    y1: int
    font_px: int
    lines: int
    inside_safe_zone: bool


def _wrap(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int
) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit(
    draw: ImageDraw.ImageDraw, card: Card, cfg: Text
) -> tuple[ImageFont.FreeTypeFont, list[str], list[float], int, int]:
    """Shrink the font until the text fits (kit textcards.py:45-54)."""
    max_w = (constants.SAFE_X1 - constants.SAFE_X0) - 2 * cfg.pad_x_px
    size = cfg.title_px if card.kind == "title" else cfg.step_px
    while True:
        font = bold(size)
        lines = _wrap(draw, card.text, font, max_w)
        widths = [draw.textlength(line, font=font) for line in lines]
        ascent, descent = font.getmetrics()
        line_h = ascent + descent
        block_h = len(lines) * line_h + (len(lines) - 1) * cfg.line_gap_px
        fits = max(widths) <= max_w and len(lines) <= cfg.max_lines
        if fits or size <= cfg.min_px:
            return font, lines, widths, line_h, block_h
        size -= cfg.shrink_step_px


def _top(position: str, box_h: int, cfg: Text) -> int:
    if position == "top":
        return constants.SAFE_Y0 + cfg.top_offset_px
    if position == "center":
        return (constants.OUT_H - box_h) // 2 + cfg.center_offset_px
    if position == "low":
        return constants.SAFE_Y1 - box_h
    raise ValueError(f"Unknown text position {position!r} (use top, center, low)")


def render_card(card: Card, out: Path, style: str, media: Media) -> TextBox:
    """Draw the text; return its bounding box and whether it is inside the safe zone."""
    cfg = media.text
    if card.kind not in KINDS:
        raise ValueError(f"Unknown text kind {card.kind!r}")
    if style not in STYLES:
        raise ValueError(f"Unknown text style {style!r}; use one of {sorted(STYLES)}")
    canvas = Image.new("RGBA", (constants.OUT_W, constants.OUT_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    font, lines, widths, line_h, block_h = _fit(draw, card, cfg)
    box_w, box_h = int(max(widths)) + 2 * cfg.pad_x_px, block_h + 2 * cfg.pad_y_px
    x0 = (constants.OUT_W - box_w) // 2
    y0 = _top(card.position, box_h, cfg)
    stroke = max(cfg.stroke_min_px, font.size // cfg.stroke_divisor)
    if style == "box":
        draw.rounded_rectangle(
            [x0, y0, x0 + box_w, y0 + box_h],
            radius=cfg.box_radius_px,
            fill=(0, 0, 0, cfg.box_alpha),
        )
    if style == "outline":  # soft drop shadow under the text
        shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        shade, y = ImageDraw.Draw(shadow), y0 + cfg.pad_y_px
        for line, width in zip(lines, widths, strict=True):
            at = ((constants.OUT_W - width) / 2 + cfg.shadow_dx_px, y + cfg.shadow_dy_px)
            dark = (0, 0, 0, cfg.shadow_alpha)
            shade.text(
                at,
                line,
                font=font,
                fill=dark,
                stroke_width=stroke + cfg.shadow_extra_stroke_px,
                stroke_fill=dark,
            )
            y += line_h + cfg.line_gap_px
        canvas = Image.alpha_composite(
            canvas, shadow.filter(ImageFilter.GaussianBlur(cfg.shadow_blur_px))
        )
        draw = ImageDraw.Draw(canvas)
    y = y0 + cfg.pad_y_px
    for line, width in zip(lines, widths, strict=True):
        outlined = style == "outline"
        draw.text(
            ((constants.OUT_W - width) / 2, y),
            line,
            font=font,
            fill=cfg.fill_rgba,
            stroke_width=stroke if outlined else 0,
            stroke_fill=cfg.outline_rgba if outlined else None,
        )
        y += line_h + cfg.line_gap_px
    canvas.save(out)
    x1, y1 = x0 + box_w, y0 + box_h
    inside = (
        x0 >= constants.SAFE_X0
        and x1 <= constants.SAFE_X1
        and y0 >= constants.SAFE_Y0
        and y1 <= constants.SAFE_Y1
    )
    return TextBox(x0, y0, x1, y1, int(font.size), len(lines), inside)
