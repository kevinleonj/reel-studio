"""Loads config/*.toml into strict models (D73, D76).

An unknown or missing key fails at load time, so a typo in a tunable cannot silently fall back to
a default. Floats are parsed as Decimal: prices and the cost cap are money.
"""

import tomllib
from decimal import Decimal
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
FACT_ID = r"^F\d+[a-z]?$"  # docs/FACTS.md row ids, e.g. F05, F21b


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------- limits.toml


class Order(_Strict):
    max_files: int
    max_total_bytes: int
    max_file_minutes: int
    lengths_s: list[int]
    default_length_s: int
    note_max_chars: int
    allowed_types: list[str]


class Quotas(_Strict):
    weekly_reels: int
    running_max: int
    lease_minutes: int
    checkout_expiry_minutes: int
    sweep_minutes: int
    missed_expiry_check_minutes: int
    paid_not_started_days: int
    poll_seconds: int
    checkout_per_minute_per_address: int
    order_calls_per_minute_per_address: int


class Retention(_Strict):
    in_days: int
    work_days: int
    out_days: int
    order_days: int


class Editor(_Strict):
    model: str
    critic_model: str
    cheap_model: str
    effort: str
    max_tokens: int
    max_tokens_retry: int
    max_turns: int
    max_renders: int
    cost_cap_usd: Decimal
    max_strips: int
    max_grade_previews: int
    strip_max_seconds: int
    haiku_drop: bool
    sdk_max_retries: int
    transient_retries: int


class Sheets(_Strict):
    tile_w: int
    tile_h: int
    cols: int
    rows: int
    frames_per_clip_min: int
    frames_per_clip_max: int
    max_image_side_px: int


class Gates(_Strict):
    hook_min: int
    category_min: int
    total_min: int


class Speech(_Strict):
    model: str
    clean_gap_ms: int
    visual_check_gap_ms: int
    pad_ms_min: int
    pad_ms_max: int
    fade_ms: int


class Codes(_Strict):
    max_redemptions: int


class Upload(_Strict):
    chunk_mib: int
    parallel_files: int
    chunk_retries: int


class Limits(_Strict):
    order: Order
    limits: Quotas
    retention: Retention
    editor: Editor
    sheets: Sheets
    gates: Gates
    speech: Speech
    codes: Codes
    upload: Upload


# ---------------------------------------------------------------- prices.toml


class _Priced(_Strict):
    fact: str = Field(pattern=FACT_ID)


class ClaudePrice(_Priced):
    """USD per million tokens; the long_* rows apply above long_prompt_threshold_tokens."""

    input: Decimal
    cache_write_5m: Decimal
    cache_read: Decimal
    output: Decimal
    long_prompt_threshold_tokens: int | None = None
    long_input: Decimal | None = None
    long_cache_write_5m: Decimal | None = None
    long_cache_read: Decimal | None = None
    long_output: Decimal | None = None


class GeminiPrice(_Priced):
    usd_per_audio_minute: Decimal


class RunJobsPrice(_Priced):
    usd_per_vcpu_second: Decimal
    usd_per_gib_second: Decimal
    free_vcpu_seconds_per_month: int
    free_gib_seconds_per_month: int


class Prices(_Strict):
    claude: dict[str, ClaudePrice]
    gemini: dict[str, GeminiPrice]
    google_cloud: dict[str, RunJobsPrice]


# ---------------------------------------------------------------- styles.toml


class Style(_Strict):
    label: str
    description: str
    skill: str
    structure: str
    voice_default: bool


class Chips(_Strict):
    items: list[str]
    exclusive: list[list[str]]


class Language(_Strict):
    code: str
    label: str


class Languages(_Strict):
    items: list[Language]


class Styles(_Strict):
    styles: dict[str, Style]
    chips: Chips
    text_languages: Languages


# ---------------------------------------------------------------- cloud.toml


class Gcp(_Strict):
    call_timeout_s: float
    retry_deadline_s: float
    retry_initial_s: float
    retry_multiplier: float
    retry_max_s: float
    signed_url_max_minutes: int


class Resend(_Strict):
    timeout_s: float
    retries: int
    backoff_s: float


class GcpProject(_Strict):
    bootstrap_services: list[str]


class Gcloud(_Strict):
    timeout_s: float


class Dns(_Strict):
    resend_region: str
    http_timeout_s: float
    http_retries: int
    backoff_s: float
    verify_poll_s: float
    verify_timeout_s: float
    record_ttl: int
    sending_key_name: str


class StripeSetup(_Strict):
    product_name: str
    unit_amount_minor: int
    currency: str
    webhook_path: str
    events: list[str]
    timeout_s: float
    max_network_retries: int


class Smoke(_Strict):
    http_timeout_s: float
    expected_max_instances: int
    expected_job_timeout_s: int
    expected_job_max_retries: int
    root_marker: str


class Cloud(_Strict):
    gcp: Gcp
    resend: Resend
    gcp_project: GcpProject
    gcloud: Gcloud
    dns: Dns
    stripe: StripeSetup
    smoke: Smoke


# ---------------------------------------------------------------- loading


class Config(_Strict):
    limits: Limits
    prices: Prices
    styles: Styles

    @model_validator(mode="after")
    def _every_model_has_a_price(self) -> Self:
        editor = self.limits.editor
        claude = {editor.model, editor.critic_model, editor.cheap_model} - set(self.prices.claude)
        gemini = {self.limits.speech.model} - set(self.prices.gemini)
        unpriced = sorted(claude | gemini)
        if unpriced:
            raise ValueError(f"no price in prices.toml for: {', '.join(unpriced)}")
        return self


def _read(path: Path) -> dict[str, Any]:  # Any: raw TOML, validated by Config right after
    with path.open("rb") as handle:
        return tomllib.load(handle, parse_float=Decimal)


def load(folder: Path = CONFIG_DIR) -> Config:
    """Read and validate limits.toml, prices.toml and styles.toml from `folder`."""
    return Config.model_validate(
        {
            "limits": _read(folder / "limits.toml"),
            "prices": _read(folder / "prices.toml"),
            "styles": _read(folder / "styles.toml"),
        }
    )


def load_cloud(folder: Path = CONFIG_DIR) -> Cloud:
    """Read and validate cloud.toml: only the cloud adapters and the STEP-08 scripts need it."""
    return Cloud.model_validate(_read(folder / "cloud.toml"))
