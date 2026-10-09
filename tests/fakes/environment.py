"""Removes every environment value a unit test could use to reach a real service."""

import pytest

from reel_studio.settings import SETTINGS_CLASSES

# Read straight from the environment by the installed SDKs, outside our Settings: Google's
# Application Default Credentials and project lookup, google-genai's key and Vertex switch,
# and the anthropic client's alternative auth and endpoint.
SDK_VARIABLES = (
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_CLOUD_PROJECT",
    "GCLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_API_KEY",
    "GOOGLE_GENAI_USE_VERTEXAI",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
)


def variable_names() -> list[str]:
    fields = [field.upper() for cls in SETTINGS_CLASSES for field in cls.model_fields]
    return [*fields, *SDK_VARIABLES]


def scrub(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in variable_names():
        monkeypatch.delenv(name, raising=False)
