"""`reel render` inside the editor image (STEP-02 task 5, D72). CI only.

On the laptop only the web lane starts containers (CLAUDE.md), and an amd64 build under
emulation is slow, so this runs where CI sets CI=true. Build time and image size are reported as
a warning so they show in the CI log (STEP-02 asks for both in the handoff).
"""

import json
import os
import shutil
import subprocess
import time
import warnings
from pathlib import Path

import pytest

from reel_studio.editor.media import qa, render

ROOT = Path(__file__).resolve().parents[3]
IMAGE = "reel-studio-editor:test"
BUILD_TIMEOUT_S = 1800
RUN_TIMEOUT_S = 1200
INSPECT_TIMEOUT_S = 60
WRITABLE_BY_ANY_UID = 0o777  # the image's user (uid 10001) writes into a host temp folder

DOCKER = shutil.which("docker")
pytestmark = pytest.mark.skipif(
    os.environ.get("CI") != "true" or DOCKER is None,
    reason="builds and runs a container: CI only (D72, CLAUDE.md lanes)",
)


class ImageReport(UserWarning):
    """Build evidence for docs/handoff/engine.md."""


def _docker(*args: str, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [str(DOCKER), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def test_reel_render_runs_inside_the_image(clips_dir: Path, tmp_path: Path) -> None:
    started = time.monotonic()
    built = _docker(
        "build",
        "--platform",
        "linux/amd64",
        "-f",
        "docker/editor.Dockerfile",
        "-t",
        IMAGE,
        str(ROOT),
        timeout=BUILD_TIMEOUT_S,
    )
    build_s = round(time.monotonic() - started)
    assert built.returncode == 0, built.stderr[-3000:]
    size = _docker(
        "image", "inspect", "-f", "{{.Size}}", IMAGE, timeout=INSPECT_TIMEOUT_S
    ).stdout.strip()
    warnings.warn(f"editor image built in {build_s} s, {size} bytes", ImageReport, stacklevel=1)

    out = tmp_path / "out"
    out.mkdir()
    out.chmod(WRITABLE_BY_ANY_UID)
    edl = ROOT / "tests" / "fixtures" / "edl"
    run = _docker(
        "run",
        "--rm",
        "--platform",
        "linux/amd64",
        "-v",
        f"{clips_dir}:/in:ro",
        "-v",
        f"{edl}:/edl:ro",
        "-v",
        f"{out}:/out",
        # EditorSettings requires the key though render never calls the API (handoff follow-up).
        "-e",
        "ANTHROPIC_API_KEY=unused-by-render",
        IMAGE,
        "render",
        "--edl",
        "/edl/basic.json",
        "/in",
        "--out",
        "/out",
        timeout=RUN_TIMEOUT_S,
    )

    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-3000:]
    assert (out / render.TEXT).exists() and (out / render.CLEAN).exists()
    checks = json.loads((out / qa.QA_JSON).read_text(encoding="utf-8"))["hard_checks"]
    assert all(v is True for v in checks.values())
