"""Deployment values: required fields, secrets, and the .env.example contract."""

import re
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from reel_studio.settings import (
    SETTINGS_CLASSES,
    AppSettings,
    CloudSettings,
    EditorSettings,
    WebSettings,
)
from tests.conftest import TEST_VALUES, MakeSettings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"
NAME = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def test_missing_required_value_fails(make_settings: MakeSettings) -> None:
    with pytest.raises(ValidationError, match="anthropic_api_key"):
        make_settings(EditorSettings, anthropic_api_key=None)


def test_secret_never_appears_in_repr(make_settings: MakeSettings) -> None:
    built = make_settings(CloudSettings)

    assert "test-cloud-anthropic-key" not in repr(built)
    assert "test-cloud-anthropic-key" not in str(built)


def test_payments_off_needs_no_stripe_key(make_settings: MakeSettings) -> None:
    built = make_settings(WebSettings)

    assert isinstance(built, WebSettings)
    assert built.stripe_secret_key is None
    assert built.ga4_measurement_id == ""


def test_payments_stripe_without_keys_fails(make_settings: MakeSettings) -> None:
    with pytest.raises(ValidationError, match="STRIPE_SECRET_KEY"):
        make_settings(WebSettings, payments="stripe")


def test_payments_stripe_with_keys_passes(make_settings: MakeSettings) -> None:
    built = make_settings(
        WebSettings, payments="stripe", stripe_secret_key="x", stripe_webhook_secret="y"
    )

    assert isinstance(built, WebSettings)
    assert built.payments == "stripe"


def test_unknown_payments_mode_fails(make_settings: MakeSettings) -> None:
    with pytest.raises(ValidationError, match="payments"):
        make_settings(WebSettings, payments="maybe")


def test_one_stripe_key_is_not_enough(make_settings: MakeSettings) -> None:
    with pytest.raises(ValidationError, match="STRIPE_WEBHOOK_SECRET"):
        make_settings(WebSettings, payments="stripe", stripe_secret_key="x")


@pytest.mark.parametrize("cls", SETTINGS_CLASSES, ids=lambda cls: cls.__name__)
def test_fresh_env_example_copy_reports_only_missing_values(
    cls: type[AppSettings], tmp_path: Path
) -> None:
    dotenv = tmp_path / ".env"
    shutil.copy(ENV_EXAMPLE, dotenv)  # what `make setup` gives a new clone

    with pytest.raises(ValidationError) as caught:
        cls(_env_file=dotenv)

    assert {error["type"] for error in caught.value.errors()} == {"missing"}


def test_blank_optional_key_is_none(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("ANTHROPIC_API_KEY=k\nGEMINI_API_KEY=\n", encoding="utf-8")

    built = EditorSettings(_env_file=dotenv)

    assert built.gemini_api_key is None


def test_blank_stripe_keys_do_not_satisfy_payments_stripe(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    lines = [
        "PAYMENTS=stripe",
        "STRIPE_SECRET_KEY=",
        "STRIPE_WEBHOOK_SECRET=",
        f"SITE_URL={TEST_VALUES['site_url']}",
        f"MAIL_FROM={TEST_VALUES['mail_from']}",
        f"KEVIN_ALERT_EMAIL={TEST_VALUES['kevin_alert_email']}",
    ]
    dotenv.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="STRIPE_SECRET_KEY"):
        WebSettings(_env_file=dotenv)


def test_every_env_example_name_has_one_field() -> None:
    names = set(NAME.findall(ENV_EXAMPLE.read_text(encoding="utf-8")))
    fields = [field.upper() for cls in SETTINGS_CLASSES for field in cls.model_fields]

    assert sorted(set(fields)) == sorted(names)
    assert len(fields) == len(set(fields)), "a variable belongs to one Settings class"
