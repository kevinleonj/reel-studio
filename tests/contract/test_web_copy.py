"""The web app's words must cover exactly what the API and config can send (no drift between
web/src/copy/en.json, reel_studio/core/errors.py, config/styles.toml and config/limits.toml)."""

import json
import re
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
    ErrorCode.PROVIDER_REJECTED,
    ErrorCode.RENDER_ERROR,
    ErrorCode.JOB_KILLED,
    ErrorCode.CLOUD_UNAVAILABLE,
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
    ErrorCode.NAME_TOO_LONG,
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


def test_every_error_code_has_a_place_on_the_page() -> None:
    # SPEND_LIMIT shows as the `paused` status, not as a failure message.
    left = set(ErrorCode) - FAILED_CODES - CHECKOUT_CODES - UPLOAD_CODES
    assert left == {ErrorCode.SPEND_LIMIT}


def test_the_page_types_every_failure_code() -> None:
    """StatusViews.tsx keys its retry map by this union, so TypeScript then checks the map."""
    types = (ROOT / "web" / "src" / "lib" / "types.ts").read_text()
    union = types.split("export type FailureCode =", 1)[1].split("\n\n", 1)[0]
    assert set(re.findall(r'"([a-z_]+)"', union)) == {str(c) for c in FAILED_CODES}


def test_upload_step_states_the_input_rules() -> None:
    """Kevin, 13 Oct 2026 (pending as D79): the clearest A/B losses were inputs, a landscape
    clip and 13.7 s of footage. The 15 is the shortest Reel on offer (D11)."""
    limits = COPY["order"]["upload"]["limits"]
    shortest = min(load().limits.order.lengths_s)
    for placeholder in ("{maxFiles}", "{maxSize}", "{maxMinutes}"):
        assert placeholder in limits
    assert "Vertical videos only." in limits
    assert f"At least {shortest} seconds of video in total." in limits
