"""prepare: proxies are 1080p-cover SDR, rotation applied, HDR tonemapped (STEP-02 task 2)."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from reel_studio.core import config, constants
from reel_studio.editor.media import prepare, tools
from tests.fixtures import make_clips

SAMPLES = 5  # frames compared for the luma check


@pytest.fixture(scope="module")
def prepared(
    clips_dir: Path, ffmpeg: tools.Ffmpeg, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, list[prepare.Proxy]]:
    work = tmp_path_factory.mktemp("work")
    return work, prepare.prepare_folder(clips_dir, work, ffmpeg, config.load_media())


def _by_source(proxies: list[prepare.Proxy], name: str) -> prepare.Proxy:
    return next(p for p in proxies if p.source == name)


def test_every_footage_file_becomes_one_proxy_in_capture_order(
    prepared: tuple[Path, list[prepare.Proxy]],
) -> None:
    _, proxies = prepared

    assert [p.id for p in proxies] == ["c01", "c02", "c03", "c04", "c05"]
    assert make_clips.STYLE_PHOTO not in {p.source for p in proxies}


def test_hdr_proxy_is_upright_sdr_bt709(
    prepared: tuple[Path, list[prepare.Proxy]], ffmpeg: tools.Ffmpeg
) -> None:
    work, proxies = prepared
    proxy = _by_source(proxies, make_clips.HDR)
    info = ffmpeg.probe(work / proxy.path)

    assert proxy.color == "hdr->sdr"
    assert (info.width, info.height) == (constants.OUT_W, constants.OUT_H)
    assert info.color_transfer == "bt709"
    assert info.pix_fmt == "yuv420p"


def test_sixty_fps_clip_keeps_sixty_and_others_get_thirty(
    prepared: tuple[Path, list[prepare.Proxy]],
) -> None:
    _, proxies = prepared

    assert _by_source(proxies, make_clips.SIXTY_FPS).fps == 60
    assert _by_source(proxies, make_clips.LANDSCAPE).fps == 30


def test_landscape_proxy_covers_the_frame_and_gains_a_silent_track(
    prepared: tuple[Path, list[prepare.Proxy]], ffmpeg: tools.Ffmpeg
) -> None:
    work, proxies = prepared
    proxy = _by_source(proxies, make_clips.LANDSCAPE)
    info = ffmpeg.probe(work / proxy.path)

    assert info.height == constants.OUT_H and info.width >= constants.OUT_W
    assert info.has_audio
    assert proxy.orientation == "landscape"


def test_photo_becomes_a_three_second_clip(
    prepared: tuple[Path, list[prepare.Proxy]], ffmpeg: tools.Ffmpeg
) -> None:
    work, proxies = prepared
    proxy = _by_source(proxies, make_clips.PHOTO)
    info = ffmpeg.probe(work / proxy.path)

    assert proxy.kind == "photo"
    assert abs(info.duration - config.load_media().prepare.photo.seconds) < 0.1
    assert info.has_audio


def test_originals_are_gone_from_the_work_folder(
    prepared: tuple[Path, list[prepare.Proxy]],
) -> None:
    work, _ = prepared

    assert not any((work / prepare.ORIGINALS).iterdir())


def _mean_luma(path: Path) -> float:
    cap = cv2.VideoCapture(str(path))
    count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    values = []
    for index in np.linspace(0, count - 1, SAMPLES):
        cap.set(cv2.CAP_PROP_POS_FRAMES, float(index))
        ok, frame = cap.read()
        assert ok
        values.append(float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean()))
    cap.release()
    return float(np.mean(values))


def test_hdr_proxy_luma_matches_an_sdr_render_of_the_same_pattern(
    prepared: tuple[Path, list[prepare.Proxy]],
    tools: make_clips.Tools,
    ffmpeg: tools.Ffmpeg,
    tmp_path: Path,
) -> None:
    work, proxies = prepared
    sdr_in, sdr_work = tmp_path / "in", tmp_path / "work"
    sdr_in.mkdir()
    make_clips.make_sdr_twin(sdr_in / make_clips.HDR, tools)
    (sdr,) = prepare.prepare_folder(sdr_in, sdr_work, ffmpeg, config.load_media())
    reference = _mean_luma(sdr_work / sdr.path)
    hdr = _mean_luma(work / _by_source(proxies, make_clips.HDR).path)
    tolerance = config.load_media().prepare.tonemap.sdr_luma_tolerance

    assert abs(hdr - reference) <= tolerance * reference, (hdr, reference)


def test_input_folder_is_untouched(clips_dir: Path) -> None:
    assert sorted(p.name for p in clips_dir.iterdir()) == sorted(make_clips.NAMES)
