"""config/*.toml loads into strict models; every price cites a fact."""

import re
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from reel_studio.core import config

FACTS = Path(__file__).resolve().parents[2] / "docs" / "FACTS.md"
FACT_ROW = re.compile(r"^\|\s*(F\d+[a-z]?)\s*\|", re.MULTILINE)


def test_repository_config_loads() -> None:
    loaded = config.load()

    assert loaded.limits.order.max_files > 0
    assert set(loaded.styles.styles) >= {"montage", "talking"}
    assert loaded.limits.editor.model in loaded.prices.claude


def test_money_is_decimal() -> None:
    loaded = config.load()

    assert isinstance(loaded.limits.editor.cost_cap_usd, Decimal)
    assert all(isinstance(p.input, Decimal) for p in loaded.prices.claude.values())


def test_every_price_cites_a_fact_in_facts_md() -> None:
    known = set(FACT_ROW.findall(FACTS.read_text(encoding="utf-8")))
    prices = config.load().prices
    tables = [*prices.claude.values(), *prices.gemini.values(), *prices.google_cloud.values()]

    assert tables
    assert {t.fact for t in tables} <= known


def _copy_config(tmp_path: Path) -> Path:
    target = tmp_path / "config"
    shutil.copytree(config.CONFIG_DIR, target)
    return target


def test_unknown_key_fails(tmp_path: Path) -> None:
    folder = _copy_config(tmp_path)
    limits = folder / "limits.toml"
    limits.write_text(limits.read_text(encoding="utf-8") + "\n[surprise]\nvalue = 1\n")

    with pytest.raises(ValidationError, match="surprise"):
        config.load(folder)


def test_price_without_fact_fails(tmp_path: Path) -> None:
    folder = _copy_config(tmp_path)
    prices = folder / "prices.toml"
    prices.write_text(prices.read_text(encoding="utf-8").replace('fact = "F37"\n', ""))

    with pytest.raises(ValidationError, match="fact"):
        config.load(folder)


def test_missing_file_fails(tmp_path: Path) -> None:
    folder = _copy_config(tmp_path)
    (folder / "styles.toml").unlink()

    with pytest.raises(FileNotFoundError):
        config.load(folder)
