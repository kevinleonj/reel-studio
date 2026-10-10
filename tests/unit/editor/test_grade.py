"""Shot match and looks as one 3D LUT per clip (kit grade.py:76-204)."""

from pathlib import Path

import numpy as np
import pytest

from reel_studio.core import config
from reel_studio.editor.media import grade
from reel_studio.editor.media.colour import ColourStats

# The float32 RGB -> Lab -> RGB round trip alone moves a pixel by up to 3.41e-3 (measured on the
# kit by the STEP-02 phase A reviewer), so identity is checked at 5e-3, not 1e-3.
IDENTITY_TOLERANCE = 5e-3
SAMPLES = 5000


def _stats(p2: float, p50: float, p98: float, neutral: tuple[float, float] | None) -> ColourStats:
    return ColourStats(
        p2=p2,
        p50=p50,
        p98=p98,
        mean=(p50, 0.0, 0.0),
        std=(20.0, 5.0, 5.0),
        neutral_frac=0.2 if neutral else 0.0,
        neutral_ab=neutral,
        clip_hi=0.0,
        crush=0.0,
    )


def _random_rgb() -> np.ndarray:
    return np.random.default_rng(7).random((SAMPLES, 3)).astype(np.float32)


@pytest.mark.parametrize("look", ["natural", "warm", "moody", "fresh", "clean", "reference"])
def test_strength_0_match_0_is_identity(look: str) -> None:
    rgb = _random_rgb()
    choice = grade.Choice(look=look, strength=0.0, match=0.0)

    out = grade.apply_transform(
        rgb, None, choice, grade.Reference(None, None), config.load_media().grade
    )

    assert np.abs(out - rgb).max() < IDENTITY_TOLERANCE


def test_unknown_look_is_refused() -> None:
    with pytest.raises(ValueError, match="Unknown look"):
        grade.apply_transform(
            _random_rgb(),
            None,
            grade.Choice("sepia", 0.6, 0.6),
            grade.Reference(None, None),
            config.load_media().grade,
        )


def test_exposure_stretch_is_clamped() -> None:
    cfg = config.load_media().grade.match
    flat = _stats(40.0, 50.0, 50.5, None)
    wide = _stats(2.0, 50.0, 99.0, None)

    assert grade.correction(flat, wide, 0.6, cfg).k == cfg.contrast_k_max
    assert grade.correction(wide, flat, 0.6, cfg).k == cfg.contrast_k_min


def test_white_balance_moves_half_way_to_the_set_cast() -> None:
    cfg = config.load_media().grade.match
    clip = _stats(10.0, 50.0, 90.0, (2.0, 8.0))
    target = _stats(10.0, 50.0, 90.0, (0.0, 4.0))

    corr = grade.correction(clip, target, 0.6, cfg)

    assert corr.shift == pytest.approx((-2.0, -6.0))


def test_cube_has_33_cubed_rows_with_red_changing_fastest(tmp_path: Path) -> None:
    path = tmp_path / "c01.cube"
    media = config.load_media()

    grade.write_cube(
        path, None, grade.Choice("natural", 0.0, 0.0), grade.Reference(None, None), media.grade
    )

    lines = path.read_text(encoding="utf-8").splitlines()
    rows = [line for line in lines if line[:1].isdigit()]
    assert "LUT_3D_SIZE 33" in lines
    assert len(rows) == 33**3
    second = [float(v) for v in rows[1].split()]
    assert second[0] == pytest.approx(1 / 32, abs=IDENTITY_TOLERANCE)
    assert second[1] == pytest.approx(0.0, abs=IDENTITY_TOLERANCE)
