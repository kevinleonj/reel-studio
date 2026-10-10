"""config/media.toml loads into strict models next to limits.toml (D76)."""

import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from reel_studio.core import config


def test_media_config_loads_with_kit_values() -> None:
    media = config.load_media()

    assert media.render.final.crf == 18  # kit render.py:299
    assert media.prepare.tonemap.algorithm == "mobius"  # kit prep.py:45
    assert media.edl.format_target_s["recipe"] == (30, 50)  # kit render.py:34


def test_sheets_carry_the_near_duplicate_threshold() -> None:
    assert config.load().limits.sheets.near_duplicate_ssim == pytest.approx(0.93)


def test_media_values_are_floats_not_decimals() -> None:
    media = config.load_media()

    assert isinstance(media.grade.default_strength, float)
    assert isinstance(media.render.loudness.true_peak_db, float)


def test_unknown_media_key_fails(tmp_path: Path) -> None:
    folder = tmp_path / "config"
    shutil.copytree(config.CONFIG_DIR, folder)
    media = folder / "media.toml"
    media.write_text(media.read_text(encoding="utf-8") + "\n[surprise]\nvalue = 1\n")

    with pytest.raises(ValidationError, match="surprise"):
        config.load_media(folder)


def test_missing_media_key_fails(tmp_path: Path) -> None:
    folder = tmp_path / "config"
    shutil.copytree(config.CONFIG_DIR, folder)
    media = folder / "media.toml"
    text = media.read_text(encoding="utf-8")
    media.write_text(text.replace("lut_size = 33", ""))

    with pytest.raises(ValidationError, match="lut_size"):
        config.load_media(folder)
