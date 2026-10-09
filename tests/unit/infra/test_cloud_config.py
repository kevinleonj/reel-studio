"""config/cloud.toml loads into a strict model, like the other config files (D73, D76)."""

import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from reel_studio.core import config


def copy_config(tmp_path: Path) -> Path:
    target = tmp_path / "config"
    shutil.copytree(config.CONFIG_DIR, target)
    return target


def test_repository_cloud_config_loads() -> None:
    cloud = config.load_cloud()

    assert cloud.stripe.unit_amount_minor > 0
    assert cloud.stripe.events == ["checkout.session.completed", "checkout.session.expired"]
    assert cloud.smoke.expected_job_max_retries == 0


def test_unknown_key_fails(tmp_path: Path) -> None:
    folder = copy_config(tmp_path)
    path = folder / "cloud.toml"
    path.write_text(path.read_text(encoding="utf-8") + "\n[gcp_typo]\nx = 1\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="gcp_typo"):
        config.load_cloud(folder)


def test_missing_key_fails(tmp_path: Path) -> None:
    folder = copy_config(tmp_path)
    path = folder / "cloud.toml"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("retries = 3\n", "", 1), encoding="utf-8")

    with pytest.raises(ValidationError, match="retries"):
        config.load_cloud(folder)


def test_missing_file_fails(tmp_path: Path) -> None:
    folder = copy_config(tmp_path)
    (folder / "cloud.toml").unlink()

    with pytest.raises(FileNotFoundError):
        config.load_cloud(folder)
