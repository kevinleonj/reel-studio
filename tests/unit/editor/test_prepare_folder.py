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


def test_a_sliver_photo_is_skipped_with_a_log_line_and_the_order_goes_on(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    folder = _videos(tmp_path, 1)
    Image.new("RGB", (10, 4300)).save(folder / "sliver.png")  # LESSONS L13

    with caplog.at_level("WARNING"):
        proxies = prepare.prepare_folder(folder, tmp_path / "w", FakeFfmpeg(), config.load_media())  # type: ignore[arg-type]

    assert [p.source for p in proxies] == ["IMG_0.MOV"]
    assert any("SKIPPED sliver.png" in r.getMessage() for r in caplog.records)


def test_a_video_whose_probe_says_width_0_is_skipped_and_the_order_goes_on(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    folder = _videos(tmp_path, 2)
    zero = {"streams": [{"codec_type": "video", "width": 0, "height": 1080}], "format": {}}
    fake = FakeFfmpeg(raw={"IMG_0.MOV": zero})  # LESSONS L13

    with caplog.at_level("WARNING"):
        proxies = prepare.prepare_folder(folder, tmp_path / "w", fake, config.load_media())  # type: ignore[arg-type]

    assert [p.source for p in proxies] == ["IMG_1.MOV"]
    assert any("SKIPPED IMG_0.MOV" in r.getMessage() for r in caplog.records)


def test_a_sliver_video_is_skipped_by_the_configured_cap(tmp_path: Path) -> None:
    folder = _videos(tmp_path, 2)
    sliver = {"streams": [{"codec_type": "video", "width": 1, "height": 10000}], "format": {}}
    fake = FakeFfmpeg(raw={"IMG_0.MOV": sliver})  # 1080 x 10,800,000 to fill the frame

    proxies = prepare.prepare_folder(folder, tmp_path / "w", fake, config.load_media())  # type: ignore[arg-type]

    assert [p.source for p in proxies] == ["IMG_1.MOV"]
