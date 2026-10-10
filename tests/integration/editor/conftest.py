"""Real ffmpeg on synthetic clips, built once per session (STEP-02 task 1).

Every test here is marked `slow`: it encodes video, so `make test-fast` skips it and `make test`
runs it. The ffmpeg used is the first one with zscale (tests/fixtures/make_clips.py).
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from reel_studio.core import config
from reel_studio.editor.media import prepare
from reel_studio.editor.media import tools as media_tools
from tests.fixtures import make_clips


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
