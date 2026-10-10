"""The web app's words must cover exactly what the API and config can send (no drift between
web/src/copy/en.json, reel_studio/core/errors.py and config/styles.toml)."""

import json
from pathlib import Path

from reel_studio.core.config import load
from reel_studio.core.errors import ErrorCode

ROOT = Path(__file__).resolve().parents[2]
COPY = json.loads((ROOT / "web" / "src" / "copy" / "en.json").read_text())

# Editor codes an order can carry while `failed`; SPEND_LIMIT shows as the `paused` status.
FAILED_CODES = {
    ErrorCode.NO_USABLE_INPUT,
    ErrorCode.MODEL_REFUSAL,
    ErrorCode.COST_CAP,
    ErrorCode.OUTPUT_TOO_LONG,
    ErrorCode.PROVIDER_UNAVAILABLE,
    ErrorCode.RENDER_ERROR,
    ErrorCode.JOB_KILLED,
}
CHECKOUT_CODES = {
    ErrorCode.CODE_INVALID,
    ErrorCode.CODE_INACTIVE,
    ErrorCode.WEEK_FULL,
    ErrorCode.RATE_LIMITED,
}
UPLOAD_CODES = {
    ErrorCode.TOO_MANY_FILES,
    ErrorCode.TOO_LARGE,
    ErrorCode.BAD_TYPE,
    ErrorCode.NO_FILES,
}


def test_every_failure_code_has_its_message() -> None:
    assert set(COPY["order"]["failed"]["messages"]) == {str(c) for c in FAILED_CODES}


def test_every_api_refusal_has_its_message() -> None:
    assert {str(c) for c in CHECKOUT_CODES} <= set(COPY["form"]["errors"])
    assert {str(c) for c in UPLOAD_CODES} <= set(COPY["order"]["upload"]["errors"])


def test_styles_and_chips_match_the_config() -> None:
    styles = load().styles
    assert set(COPY["styles"]) == set(styles.styles)
    for key, style in styles.styles.items():
        assert COPY["styles"][key] == {"label": style.label, "description": style.description}
    assert set(COPY["chips"]) == set(styles.chips.items)
    assert set(COPY["textLanguages"]) == {item.code for item in styles.text_languages.items}
