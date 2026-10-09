"""Removes every environment value a unit test could use to reach a real service."""

import pytest

from reel_studio.settings import SETTINGS_CLASSES

# Google client libraries find credentials and a project through these (Application Default
# Credentials), so a test must not inherit them from the developer's shell.
GOOGLE_VARIABLES = ("GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT")


def variable_names() -> list[str]:
    fields = [field.upper() for cls in SETTINGS_CLASSES for field in cls.model_fields]
    return [*fields, *GOOGLE_VARIABLES]


def scrub(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in variable_names():
        monkeypatch.delenv(name, raising=False)
