"""prepare_folder with a fake ffmpeg: staging, skips and NoUsableInput (STEP-02 task 2)."""

from collections.abc import Sequence
from pathlib import Path

import pytest
from PIL import Image

from reel_studio.core import config
from reel_studio.core.errors import NoUsableInput
from reel_studio.editor.media import prepare
from tests.fakes.ffmpeg import FakeFfmpeg


def _videos(tmp_path: Path, count: int) -> Path:
    folder = tmp_path / "in"
    folder.mkdir()
    for i in range(count):
        (folder / f"IMG_{i}.MOV").write_bytes(bytes(i + 1))
    return folder


def test_only_one_original_is_on_disk_at_a_time(tmp_path: Path) -> None:
    folder, work = _videos(tmp_path, 3), tmp_path / "work"
    seen: list[int] = []

    def look(_: Sequence[str]) -> None:
        seen.append(len(list((work / prepare.ORIGINALS).iterdir())))

    fake = FakeFfmpeg(on_run=look)

    proxies = prepare.prepare_folder(folder, work, fake, config.load_media())  # type: ignore[arg-type]

    assert len(proxies) == 3
    assert seen == [1, 1, 1]
    assert not any((work / prepare.ORIGINALS).iterdir())


def test_empty_folder_has_no_usable_input(tmp_path: Path) -> None:
    folder = tmp_path / "in"
    folder.mkdir()

    with pytest.raises(NoUsableInput):
        prepare.prepare_folder(folder, tmp_path / "w", FakeFfmpeg(), config.load_media())  # type: ignore[arg-type]


def test_all_unreadable_is_no_usable_input_and_says_how_many(tmp_path: Path) -> None:
    folder = _videos(tmp_path, 2)
    fake = FakeFfmpeg(unreadable={"IMG_0.MOV", "IMG_1.MOV"})

    with pytest.raises(NoUsableInput, match="2 file"):
        prepare.prepare_folder(folder, tmp_path / "w", fake, config.load_media())  # type: ignore[arg-type]


def test_a_decompression_bomb_photo_is_skipped_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _videos(tmp_path, 1)
    (folder / "huge.png").write_bytes(b"png")

    def bomb(*_: object, **__: object) -> None:
        raise Image.DecompressionBombError("too many pixels")

    monkeypatch.setattr("reel_studio.editor.media.prepare.Image.open", bomb)

    proxies = prepare.prepare_folder(folder, tmp_path / "w", FakeFfmpeg(), config.load_media())  # type: ignore[arg-type]

    assert [p.source for p in proxies] == ["IMG_0.MOV"]
