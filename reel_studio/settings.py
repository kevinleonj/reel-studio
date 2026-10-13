"""Deployment values, read from `.env` by pydantic-settings (D76).

One class per consumer, so each process holds only the values it needs (D62: the website never
holds the Anthropic or Gemini key). A field without a default is required: a missing value stops
the process at startup with the variable's name. Every default says why it exists.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = ".env"
# jobs.run takes the job's full resource name (F92); a short name would fail at the first Start.
JOB_NAME = re.compile(r"^projects/[^/]+/locations/[^/]+/jobs/[^/]+$")


class _Base(BaseSettings):
    # extra="ignore": .env holds every tier's variables; each class reads only its own.
    # hide_input_in_errors: a model-level rule makes pydantic print the input, which holds keys
    # (task 2 review C1).
    # env_ignore_empty: a blank `KEY=` (as copied from .env.example) counts as missing, so a
    # required value fails by name and an optional one falls back to its default (F81).
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )


class EditorSettings(_Base):
    """The editor: `reel make` on the laptop and the render job in the cloud."""

    anthropic_api_key: SecretStr
    gemini_api_key: SecretStr | None = None  # default-because: optional; no key = voice off (D14)
    # Absolute paths, no PATH lookup: Homebrew's ffmpeg-full (zscale) is keg-only on the Mac,
    # the image uses Debian's ffmpeg (D72). Whether the file runs is checked where it is used.
    ffmpeg_path: Path
    ffprobe_path: Path

    @field_validator("ffmpeg_path", "ffprobe_path")
    @classmethod
    def _absolute(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError(f"must be an absolute path to the binary, not {value}")
        return value


class BuildSettings(_Base):
    """Build-step tools only: `make eval` and `make ab` (STEP-03, STEP-04)."""

    old_kit_dir: Path
    reel_fixtures_dir: Path


@dataclass(frozen=True)
class LaptopRuntime:
    smtp_host: str
    smtp_port: int
    data_dir: Path


@dataclass(frozen=True)
class CloudRuntime:
    gcs_bucket: str
    editor_job: str
    resend_sending_key: SecretStr


class RuntimeSettings(_Base):
    """Where orders live and how mail leaves: the website and the editor that runs orders both
    read these, without holding each other's keys (D62). TIER says which adapters to build:
    `laptop` (Firestore emulator, Mailpit, a data folder) or `cloud` (Cloud Run: Firestore,
    Resend, Cloud Storage, the editor job). It is set on purpose, never guessed from the
    environment (MAIN-NEXT task 2)."""

    tier: Literal["laptop", "cloud"]
    site_url: str
    mail_from: str
    kevin_alert_email: str
    # The emulator's project id on the laptop (the client finds the emulator through
    # FIRESTORE_EMULATOR_HOST itself, F308); the real project on Cloud Run.
    firestore_project: str
    # TIER=laptop: Mailpit's SMTP address (F309) and the filesystem Storage root.
    smtp_host: str | None = None  # default-because: TIER=cloud mails through Resend
    smtp_port: int | None = None  # default-because: TIER=cloud mails through Resend
    data_dir: Path | None = None  # default-because: TIER=cloud keeps files in Cloud Storage
    # TIER=cloud: names Terraform sets (infra/main/locals.tf) and Resend's sending-only key.
    gcs_bucket: str | None = None  # default-because: TIER=laptop keeps files in DATA_DIR
    editor_job: str | None = None  # default-because: TIER=laptop runs the editor itself
    resend_sending_key: SecretStr | None = None  # default-because: TIER=laptop mails by SMTP

    @field_validator("editor_job")
    @classmethod
    def _full_job_name(cls, value: str | None) -> str | None:
        if value is not None and not JOB_NAME.match(value):
            raise ValueError("must be projects/<project>/locations/<region>/jobs/<name>")
        return value

    @model_validator(mode="after")
    def _tier_needs_its_values(self) -> Self:
        needed = (
            {"SMTP_HOST": self.smtp_host, "SMTP_PORT": self.smtp_port, "DATA_DIR": self.data_dir}
            if self.tier == "laptop"
            else {
                "GCS_BUCKET": self.gcs_bucket,
                "EDITOR_JOB": self.editor_job,
                "RESEND_SENDING_KEY": self.resend_sending_key,
            }
        )
        missing = [name for name, value in needed.items() if value is None]
        if missing:
            raise ValueError(f"TIER={self.tier} needs {', '.join(missing)}")
        return self

    def laptop(self) -> LaptopRuntime:
        if self.smtp_host is None or self.smtp_port is None or self.data_dir is None:
            raise ValueError("TIER=laptop values are not set")
        return LaptopRuntime(self.smtp_host, self.smtp_port, self.data_dir)

    def cloud(self) -> CloudRuntime:
        key = self.resend_sending_key
        if self.gcs_bucket is None or self.editor_job is None or key is None:
            raise ValueError("TIER=cloud values are not set")
        return CloudRuntime(self.gcs_bucket, self.editor_job, key)


class JobSettings(_Base):
    """One reel-editor execution on Cloud Run: the overrides the launcher sets per execution
    (ARCHITECTURE §4, gcp_launcher ORDER_ID_ENV and RUN_TOKEN_ENV)."""

    order_id: str
    run_token: SecretStr  # the run's one-time start credential: never logged


class WebSettings(_Base):
    """The website and its API (Tier 1 on the laptop, Tier 2 in the cloud)."""

    payments: Literal["off", "stripe"]
    stripe_secret_key: SecretStr | None = None  # default-because: unused when PAYMENTS=off
    stripe_webhook_secret: SecretStr | None = None  # default-because: unused when PAYMENTS=off
    # STEP-07: the €19 price (`make stripe-setup`) and the 100%-off coupon that `reelctl codes
    # create` attaches promotion codes to. Ids, not secrets.
    stripe_price_id: str | None = None  # default-because: unused when PAYMENTS=off
    stripe_coupon_id: str | None = None  # default-because: unused when PAYMENTS=off
    ga4_measurement_id: str = ""  # default-because: empty = analytics off (D75)
    google_ads_id: str = ""  # default-because: empty = ads off (D75)
    web_dist: Path  # the Astro build the API serves
    # D14, D62: this service never holds the Gemini key, so it is told whether voice works.
    voice_available: bool

    @model_validator(mode="after")
    def _stripe_needs_keys(self) -> Self:
        if self.payments != "stripe":
            return self
        needed = {
            "STRIPE_SECRET_KEY": self.stripe_secret_key,
            "STRIPE_WEBHOOK_SECRET": self.stripe_webhook_secret,
            "STRIPE_PRICE_ID": self.stripe_price_id,
            "STRIPE_COUPON_ID": self.stripe_coupon_id,
        }
        missing = [name for name, value in needed.items() if value is None]
        if missing:
            raise ValueError(f"PAYMENTS=stripe needs {', '.join(missing)}")
        return self


class CloudSettings(_Base):
    """Google Cloud setup from the laptop: Terraform inputs, secrets push, DNS (STEP-08)."""

    gcp_project: str
    gcp_region: str
    gcp_billing_account: str
    cloud_anthropic_api_key: SecretStr
    cloud_gemini_api_key: SecretStr
    resend_api_key: SecretStr
    cloudflare_api_token: SecretStr
    email_domain: str


AppSettings = (
    EditorSettings | BuildSettings | RuntimeSettings | JobSettings | WebSettings | CloudSettings
)
SETTINGS_CLASSES: tuple[type[_Base], ...] = (
    EditorSettings,
    BuildSettings,
    RuntimeSettings,
    JobSettings,
    WebSettings,
    CloudSettings,
)
