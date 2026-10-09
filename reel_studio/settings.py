"""Deployment values, read from `.env` by pydantic-settings (D76).

One class per consumer, so each process holds only the values it needs (D62: the website never
holds the Anthropic or Gemini key). A field without a default is required: a missing value stops
the process at startup with the variable's name. Every default says why it exists.
"""

from pathlib import Path
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = ".env"


class _Base(BaseSettings):
    # extra="ignore": .env holds every tier's variables; each class reads only its own.
    model_config = SettingsConfigDict(
        env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore", frozen=True
    )


class EditorSettings(_Base):
    """The editor: `reel make` on the laptop and the render job in the cloud."""

    anthropic_api_key: SecretStr
    gemini_api_key: SecretStr | None = None  # default-because: optional; no key = voice off (D14)


class BuildSettings(_Base):
    """Build-step tools only: `make eval` and `make ab` (STEP-03, STEP-04)."""

    old_kit_dir: Path
    reel_fixtures_dir: Path


class WebSettings(_Base):
    """The website and its API (Tier 1 on the laptop, Tier 2 in the cloud)."""

    payments: Literal["off", "stripe"]
    stripe_secret_key: SecretStr | None = None  # default-because: unused when PAYMENTS=off
    stripe_webhook_secret: SecretStr | None = None  # default-because: unused when PAYMENTS=off
    site_url: str
    mail_from: str
    kevin_alert_email: str
    ga4_measurement_id: str = ""  # default-because: empty = analytics off (D75)
    google_ads_id: str = ""  # default-because: empty = ads off (D75)

    @model_validator(mode="after")
    def _stripe_needs_keys(self) -> Self:
        if self.payments == "stripe" and (
            self.stripe_secret_key is None or self.stripe_webhook_secret is None
        ):
            raise ValueError("PAYMENTS=stripe needs STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET")
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
