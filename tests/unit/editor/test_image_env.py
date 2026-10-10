"""The editor image's ENV satisfies EditorSettings, except the API keys (TONIGHT.md, D72).

EditorSettings has no default for the ffmpeg paths, so a container without them would stop at
startup. The keys are secrets: Cloud Run injects them, the image never holds them.
"""

import re
from pathlib import Path

from reel_studio.settings import EditorSettings

DOCKERFILE = Path(__file__).resolve().parents[3] / "docker" / "editor.Dockerfile"
SECRETS = {"anthropic_api_key", "gemini_api_key"}  # come from Cloud Run, never the image
ENV_NAME = re.compile(r"\b([A-Z][A-Z0-9_]*)=")


def _image_env() -> set[str]:
    """Variable names set by ENV instructions, including continuation lines."""
    text = DOCKERFILE.read_text(encoding="utf-8").replace("\\\n", " ")
    names: set[str] = set()
    for line in text.splitlines():
        if line.strip().startswith("ENV "):
            names |= set(ENV_NAME.findall(line))
    return names


def test_every_required_setting_but_the_keys_is_in_the_image_env() -> None:
    required = {name for name, field in EditorSettings.model_fields.items() if field.is_required()}

    missing = {name.upper() for name in required - SECRETS} - _image_env()

    assert required - SECRETS, "EditorSettings should require the ffmpeg paths"
    assert not missing, f"docker/editor.Dockerfile ENV lacks {sorted(missing)}"


def test_the_image_points_at_debians_ffmpeg() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")

    assert "FFMPEG_PATH=/usr/bin/ffmpeg" in text
    assert "FFPROBE_PATH=/usr/bin/ffprobe" in text
