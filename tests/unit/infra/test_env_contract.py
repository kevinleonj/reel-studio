"""The env contract (docs/INFRA.md §4): what Terraform gives reel-api and the editor job is
enough for the settings each one reads on Cloud Run (TIER=cloud), with no value left to guess."""

import re
from pathlib import Path
from typing import Any

import hcl2
import pytest
from pydantic import ValidationError

from reel_studio.settings import RuntimeSettings, WebSettings

LOCALS = Path(__file__).resolve().parents[3] / "infra" / "main" / "locals.tf"
INTERPOLATION = re.compile(r"\$\{[^}]*\}")
STAND_IN = "x"  # every value Terraform computes; the settings check shapes, not projects


def terraform_locals() -> dict[str, Any]:
    with LOCALS.open(encoding="utf-8") as handle:
        parsed = hcl2.load(handle)
    merged: dict[str, Any] = {}
    for block in parsed["locals"]:
        merged.update(block)
    return merged


def _values(*maps: str) -> dict[str, Any]:
    """Plain values as Terraform writes them; computed parts replaced by a stand-in."""
    found = terraform_locals()
    values: dict[str, Any] = {}
    for name in maps:
        for key, value in found[name].items():
            text = str(value).removeprefix('"').removesuffix('"')  # python-hcl2 keeps quotes
            values[key.lower()] = INTERPOLATION.sub(STAND_IN, text)
    return values


def test_reel_api_gets_every_value_its_settings_need() -> None:
    values = _values("common_env", "api_env", "api_secrets")
    try:
        WebSettings(_env_file=None, **values)
        runtime = RuntimeSettings(_env_file=None, **values)
    except ValidationError as error:
        pytest.fail(f"reel-api settings refuse Terraform's env: {error}")
    assert runtime.tier == "cloud"


def test_the_editor_job_gets_every_runtime_value() -> None:
    values = _values("common_env", "editor_secrets")
    try:
        runtime = RuntimeSettings(_env_file=None, **values)
    except ValidationError as error:
        pytest.fail(f"the editor job's settings refuse Terraform's env: {error}")
    assert runtime.tier == "cloud"


def test_the_editor_job_holds_no_stripe_secret() -> None:
    # D62 and ARCHITECTURE §6: Stripe's keys are read by reel-api only.
    assert not {k for k in terraform_locals()["editor_secrets"] if k.startswith("STRIPE_")}
