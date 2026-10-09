"""Real ffmpeg on synthetic clips, built once per session (STEP-02 task 1).

Every test here is marked `slow`: it encodes video, so `make test-fast` skips it and `make test`
runs it. The ffmpeg used is the first one with zscale (tests/fixtures/make_clips.py).
"""

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from reel_studio.core import config
from reel_studio.editor.media import prepare
from reel_studio.editor.media import tools as media_tools
from tests.fixtures import make_clips

PROBE_TIMEOUT_S = 60


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    here = Path(__file__).parent
    for item in items:
        if here in Path(item.path).parents:
            item.add_marker(pytest.mark.slow)


@pytest.fixture(scope="session")
def tools() -> make_clips.Tools:
    return make_clips.find_tools()


@pytest.fixture(scope="session")
def clips_dir(tmp_path_factory: pytest.TempPathFactory, tools: make_clips.Tools) -> Iterator[Path]:
    folder = tmp_path_factory.mktemp("clips")
    make_clips.make(folder, tools)
    yield folder


def probe(tools: make_clips.Tools, path: Path) -> dict[str, Any]:  # Any: ffprobe JSON
    done = subprocess.run(  # noqa: S603 - fixed argv built here, no shell
        [
            str(tools.ffprobe),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=PROBE_TIMEOUT_S,
    )
    data: dict[str, Any] = json.loads(done.stdout)
    return data


@pytest.fixture(scope="session")
def ffmpeg(tools: make_clips.Tools) -> media_tools.Ffmpeg:
    return media_tools.Ffmpeg(tools.ffmpeg, tools.ffprobe, config.load_media().tools)


@pytest.fixture(scope="session")
def prepared(
    clips_dir: Path, ffmpeg: media_tools.Ffmpeg, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, list[prepare.Proxy]]:
    """The fixture clips through prepare once; tests read the proxies, never write them."""
    work = tmp_path_factory.mktemp("work")
    return work, prepare.prepare_folder(clips_dir, work, ffmpeg, config.load_media())
