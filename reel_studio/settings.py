"""Deployment values, read from `.env` by pydantic-settings (D76).

One class per consumer, so each process holds only the values it needs (D62: the website never
holds the Anthropic or Gemini key). A field without a default is required: a missing value stops
the process at startup with the variable's name. Every default says why it exists.
"""

from pathlib import Path
from typing import Literal, Self

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = ".env"


class _Base(BaseSettings):
    # extra="ignore": .env holds every tier's variables; each class reads only its own.
    # env_ignore_empty: a blank `KEY=` (as copied from .env.example) counts as missing, so a
    # required value fails by name and an optional one falls back to its default (F81).
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        frozen=True,
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


class WebSettings(_Base):
    """The website and its API (Tier 1 on the laptop, Tier 2 in the cloud)."""

    payments: Literal["off", "stripe"]
    stripe_secret_key: SecretStr | None = None  # default-because: unused when PAYMENTS=off
    stripe_webhook_secret: SecretStr | None = None  # default-because: unused when PAYMENTS=off
    # STEP-07: the €19 price (`make stripe-setup`) and the 100%-off coupon that `reelctl codes
    # create` attaches promotion codes to. Ids, not secrets.
    stripe_price_id: str | None = None  # default-because: unused when PAYMENTS=off
    stripe_coupon_id: str | None = None  # default-because: unused when PAYMENTS=off
    site_url: str
    mail_from: str
    kevin_alert_email: str
    ga4_measurement_id: str = ""  # default-because: empty = analytics off (D75)
    google_ads_id: str = ""  # default-because: empty = ads off (D75)
    # Laptop runtime (STEP-06): the Firestore emulator's project id (the client finds the
    # emulator through FIRESTORE_EMULATOR_HOST itself, F308), Mailpit's SMTP address (F309),
    # the filesystem Storage root and the Astro build the API serves.
    firestore_project: str
    smtp_host: str
    smtp_port: int
    data_dir: Path
    web_dist: Path
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


AppSettings = EditorSettings | BuildSettings | WebSettings | CloudSettings
SETTINGS_CLASSES: tuple[type[_Base], ...] = (
    EditorSettings,
    BuildSettings,
    WebSettings,
    CloudSettings,
)
