"""Deployment values: required fields, secrets, and the .env.example contract."""

import re
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from reel_studio.settings import (
    SETTINGS_CLASSES,
    AppSettings,
    CloudProjectSettings,
    CloudSettings,
    EditorSettings,
    RuntimeSettings,
    WebSettings,
)
from tests.conftest import TEST_VALUES, MakeSettings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"
NAME = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def test_missing_required_value_fails(make_settings: MakeSettings) -> None:
    with pytest.raises(ValidationError, match="anthropic_api_key"):
        make_settings(EditorSettings, anthropic_api_key=None)


def test_editor_requires_ffmpeg_paths_with_no_default() -> None:
    with pytest.raises(ValidationError) as caught:
        EditorSettings(_env_file=None, anthropic_api_key="k")

    missing = {(e["loc"], e["type"]) for e in caught.value.errors()}
    assert missing == {(("ffmpeg_path",), "missing"), (("ffprobe_path",), "missing")}


@pytest.mark.parametrize("field", ["ffmpeg_path", "ffprobe_path"])
@pytest.mark.parametrize("value", ["ffmpeg", "bin/ffmpeg", "~/bin/ffmpeg", "."])
def test_editor_ffmpeg_paths_must_be_absolute(
    make_settings: MakeSettings, field: str, value: str
) -> None:
    # Homebrew's ffmpeg-full is keg-only, so a PATH lookup on the Mac finds the wrong binary.
    with pytest.raises(ValidationError, match="absolute"):
        make_settings(EditorSettings, **{field: value})


def test_secret_never_appears_in_repr(make_settings: MakeSettings) -> None:
    built = make_settings(CloudSettings)

    assert "test-cloud-anthropic-key" not in repr(built)
    assert "test-cloud-anthropic-key" not in str(built)


def test_the_project_setup_holds_no_key() -> None:
    """`make gcp-project` and `make bootstrap-plan` read only the project values; the four API
    keys stay in CloudSettings for the commands that use them (Kevin, 13 Oct 2026)."""
    built = CloudProjectSettings(
        _env_file=None,
        gcp_project="test-project",
        gcp_region="test-region",
        gcp_billing_account="000000-000000-000000",
    )

    assert set(CloudProjectSettings.model_fields) == {
        "gcp_project",
        "gcp_region",
        "gcp_billing_account",
    }
    assert built.gcp_project == "test-project"
    assert not {f for f in CloudSettings.model_fields if f.startswith("gcp_")}


def test_payments_off_needs_no_stripe_key(make_settings: MakeSettings) -> None:
    built = make_settings(WebSettings)

    assert isinstance(built, WebSettings)
    assert built.stripe_secret_key is None
    assert built.ga4_measurement_id == ""


def test_payments_stripe_without_keys_fails(make_settings: MakeSettings) -> None:
    with pytest.raises(ValidationError, match="STRIPE_SECRET_KEY"):
        make_settings(WebSettings, payments="stripe")


STRIPE_VALUES = {
    "stripe_secret_key": "x",
    "stripe_webhook_secret": "y",
    "stripe_price_id": "price_test",
    "stripe_coupon_id": "coupon_test",
}


def test_payments_stripe_with_keys_and_ids_passes(make_settings: MakeSettings) -> None:
    built = make_settings(WebSettings, payments="stripe", **STRIPE_VALUES)

    assert isinstance(built, WebSettings)
    assert built.payments == "stripe"
    assert built.stripe_price_id == "price_test"
    assert built.stripe_coupon_id == "coupon_test"


def test_payments_off_needs_no_stripe_ids(make_settings: MakeSettings) -> None:
    # web.md, For MAIN (STEP-07): the €19 price and the 100%-off coupon exist only with Stripe.
    built = make_settings(WebSettings)

    assert isinstance(built, WebSettings)
    assert built.stripe_price_id is None
    assert built.stripe_coupon_id is None


@pytest.mark.parametrize("missing", sorted(STRIPE_VALUES))
def test_payments_stripe_needs_every_stripe_value(
    make_settings: MakeSettings, missing: str
) -> None:
    values = {k: v for k, v in STRIPE_VALUES.items() if k != missing}

    with pytest.raises(ValidationError, match=missing.upper()):
        make_settings(WebSettings, payments="stripe", **values)


def test_unknown_payments_mode_fails(make_settings: MakeSettings) -> None:
    with pytest.raises(ValidationError, match="payments"):
        make_settings(WebSettings, payments="maybe")


def test_web_requires_its_laptop_runtime_values() -> None:
    # docs/handoff/web.md, Needs Kevin: the laptop API and dispatcher (STEP-06 task 6).
    with pytest.raises(ValidationError) as caught:
        WebSettings(_env_file=None, payments="off")

    missing = {e["loc"][0] for e in caught.value.errors() if e["type"] == "missing"}
    assert missing == {"web_dist", "voice_available"}


def test_runtime_requires_where_orders_live_and_how_mail_leaves() -> None:
    with pytest.raises(ValidationError) as caught:
        RuntimeSettings(_env_file=None)

    missing = {e["loc"][0] for e in caught.value.errors() if e["type"] == "missing"}
    assert missing == {"tier", "site_url", "mail_from", "kevin_alert_email", "firestore_project"}


def test_web_runtime_values_are_typed(make_settings: MakeSettings) -> None:
    web = make_settings(WebSettings, voice_available="false")
    runtime = make_settings(RuntimeSettings, smtp_port="1025")

    assert isinstance(web, WebSettings)
    assert isinstance(runtime, RuntimeSettings)
    assert runtime.smtp_port == 1025
    assert web.voice_available is False
    assert isinstance(runtime.data_dir, Path)
    assert isinstance(web.web_dist, Path)


def test_smtp_port_must_be_a_number(make_settings: MakeSettings) -> None:
    with pytest.raises(ValidationError, match="smtp_port"):
        make_settings(RuntimeSettings, smtp_port="mailpit")


def test_one_stripe_key_is_not_enough(make_settings: MakeSettings) -> None:
    with pytest.raises(ValidationError, match="STRIPE_WEBHOOK_SECRET"):
        make_settings(WebSettings, payments="stripe", stripe_secret_key="x")


# The laptop values .env.example fills are all WebSettings needs; every other class waits for
# a key, a path or an address only the person running it has.
LOADS_FROM_THE_EXAMPLE = {WebSettings}


@pytest.mark.parametrize("cls", SETTINGS_CLASSES, ids=lambda cls: cls.__name__)
def test_fresh_env_example_copy_reports_only_missing_values(
    cls: type[AppSettings], tmp_path: Path
) -> None:
    dotenv = tmp_path / ".env"
    shutil.copy(ENV_EXAMPLE, dotenv)  # what `make setup` gives a new clone

    if cls in LOADS_FROM_THE_EXAMPLE:
        cls(_env_file=dotenv)
        return
    with pytest.raises(ValidationError) as caught:
        cls(_env_file=dotenv)
    assert {error["type"] for error in caught.value.errors()} == {"missing"}


def test_blank_optional_key_is_none(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    lines = [
        "ANTHROPIC_API_KEY=k",
        "GEMINI_API_KEY=",
        f"FFMPEG_PATH={TEST_VALUES['ffmpeg_path']}",
        f"FFPROBE_PATH={TEST_VALUES['ffprobe_path']}",
    ]
    dotenv.write_text("\n".join(lines) + "\n", encoding="utf-8")

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
        *(
            f"{name.upper()}={TEST_VALUES[name]}"
            for name in ("firestore_project", "smtp_host", "smtp_port", "data_dir", "web_dist")
        ),
        f"VOICE_AVAILABLE={str(TEST_VALUES['voice_available']).lower()}",
    ]
    dotenv.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="STRIPE_SECRET_KEY"):
        WebSettings(_env_file=dotenv)


def test_every_env_example_name_has_one_field() -> None:
    names = set(NAME.findall(ENV_EXAMPLE.read_text(encoding="utf-8")))
    fields = [field.upper() for cls in SETTINGS_CLASSES for field in cls.model_fields]

    assert sorted(set(fields)) == sorted(names)
    assert len(fields) == len(set(fields)), "a variable belongs to one Settings class"


CLOUD_VALUES = {
    "tier": "cloud",
    "gcs_bucket": "reel-studio-media-test",
    "editor_job": "projects/test-project/locations/test-region/jobs/reel-editor",
    "resend_sending_key": "test-sending-key",
}


def test_a_settings_error_never_echoes_a_key(make_settings: MakeSettings) -> None:
    """A model-level rule makes pydantic print the input, cut in the middle: the last field,
    the Resend key, kept its tail (task 2 review C1)."""
    key = "sending-key-QwErTyUiOpAsDfGhJkLzXc"
    with pytest.raises(ValidationError) as caught:
        make_settings(
            RuntimeSettings, **{**CLOUD_VALUES, "editor_job": None, "resend_sending_key": key}
        )
    text = str(caught.value)
    assert "EDITOR_JOB" in text
    assert not [key[i : i + 6] for i in range(len(key) - 5) if key[i : i + 6] in text]


def test_the_tier_is_chosen_never_defaulted() -> None:
    assert RuntimeSettings.model_fields["tier"].is_required()


def test_the_laptop_tier_needs_smtp_and_a_data_folder(make_settings: MakeSettings) -> None:
    with pytest.raises(ValidationError) as caught:
        make_settings(RuntimeSettings, tier="laptop", smtp_host=None, data_dir=None)
    assert "TIER=laptop needs SMTP_HOST, DATA_DIR" in str(caught.value)


def test_the_cloud_tier_needs_the_bucket_the_job_and_the_sending_key(
    make_settings: MakeSettings,
) -> None:
    with pytest.raises(ValidationError) as caught:
        make_settings(RuntimeSettings, tier="cloud")
    assert "TIER=cloud needs GCS_BUCKET, EDITOR_JOB, RESEND_SENDING_KEY" in str(caught.value)


def test_the_cloud_tier_needs_no_smtp_or_data_folder(make_settings: MakeSettings) -> None:
    built = make_settings(
        RuntimeSettings, smtp_host=None, smtp_port=None, data_dir=None, **CLOUD_VALUES
    )
    assert isinstance(built, RuntimeSettings)
    cloud = built.cloud()
    assert cloud.gcs_bucket == CLOUD_VALUES["gcs_bucket"]
    assert cloud.resend_sending_key.get_secret_value() == CLOUD_VALUES["resend_sending_key"]
    with pytest.raises(ValueError, match="TIER=laptop"):
        built.laptop()


def test_the_laptop_view_has_no_optional_values(make_settings: MakeSettings) -> None:
    built = make_settings(RuntimeSettings, tier="laptop")
    assert isinstance(built, RuntimeSettings)
    laptop = built.laptop()
    assert (laptop.smtp_host, laptop.smtp_port) == (TEST_VALUES["smtp_host"], 1025)
    with pytest.raises(ValueError, match="TIER=cloud"):
        built.cloud()


@pytest.mark.parametrize(
    "job", ["reel-editor", "projects/p/jobs/reel-editor", "projects/p/locations/r/jobs/"]
)
def test_the_editor_job_is_its_full_resource_name(make_settings: MakeSettings, job: str) -> None:
    # The launcher passes it to jobs.run as `name` (F30), so a short name fails at the first Start.
    with pytest.raises(ValidationError, match="editor_job"):
        make_settings(RuntimeSettings, **{**CLOUD_VALUES, "editor_job": job})
