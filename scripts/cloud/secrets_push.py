"""`make secrets-push`: copy the three cloud secrets from .env into Secret Manager.

docs/ARCHITECTURE.md §6: only CLOUD_ANTHROPIC_API_KEY, CLOUD_GEMINI_API_KEY and STRIPE_SECRET_KEY.
The Resend key and the webhook secret are created by `make dns` and `make stripe-setup`. Values
go on gcloud's stdin and are never printed. Each run adds a new version, confirms it is enabled,
then destroys the older versions (billed while enabled or disabled, and still readable; F413).
"""

import sys

from pydantic import SecretStr

from reel_studio.core.config import load_cloud
from reel_studio.settings import CloudSettings, WebSettings
from scripts.cloud._shell import CommandError, Runner, rotate_secret, run, say

# settings field -> Secret Manager container (infra/bootstrap/locals.tf secret_ids)
SECRET_FIELDS = {
    "cloud_anthropic_api_key": "anthropic-api-key",
    "cloud_gemini_api_key": "gemini-api-key",  # hardcode-ok: container name, not a model
    "stripe_secret_key": "stripe-secret-key",
}


def push_all(runner: Runner, project: str, values: dict[str, SecretStr], timeout_s: float) -> None:
    for secret_id, value in values.items():
        version = rotate_secret(runner, project, secret_id, value, timeout_s)
        say(f"secrets-push: {secret_id} now at version {version}, older versions destroyed")


def main() -> int:
    cloud = CloudSettings()
    web = WebSettings()
    if web.stripe_secret_key is None:
        say("secrets-push: STRIPE_SECRET_KEY is not set in .env")
        return 1
    values = {
        SECRET_FIELDS["cloud_anthropic_api_key"]: cloud.cloud_anthropic_api_key,
        SECRET_FIELDS["cloud_gemini_api_key"]: cloud.cloud_gemini_api_key,
        SECRET_FIELDS["stripe_secret_key"]: web.stripe_secret_key,
    }
    try:
        push_all(run, cloud.gcp_project, values, load_cloud().gcloud.timeout_s)
    except (CommandError, ValueError) as exc:
        say(f"secrets-push: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
