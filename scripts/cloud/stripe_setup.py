"""`make stripe-setup MODE=test|live`: product, one-time price and the cloud webhook endpoint.

D58: product "Reel", a one-time price, and a webhook for checkout.session.completed and
.expired (F23). The endpoint's signing secret goes straight to Secret Manager on gcloud's stdin
and is never printed. Safe to run twice: the price is found by its lookup key, and an endpoint
with the same URL is kept (its secret is only returned at creation, so it is not re-pushed).
"""

import argparse
import sys
from typing import Any

import stripe
from pydantic import SecretStr

from reel_studio.core.config import StripeSetup, load_cloud
from reel_studio.settings import CloudSettings, WebSettings
from scripts.cloud._shell import (
    CommandError,
    GcloudSecrets,
    Runner,
    SecretStore,
    run,
    say,
    service_url,
)

STRIPE_API_VERSION = "2026-09-30.endive"  # F19
WEBHOOK_SECRET_ID = "stripe-webhook-secret"  # noqa: S105 - a container name (infra/bootstrap)
# Secret and restricted key prefixes per mode (Stripe API keys documentation).
KEY_PREFIXES = {"test": ("sk_test_", "rk_test_"), "live": ("sk_live_", "rk_live_")}


class SetupError(Exception):
    """The vendor side and Secret Manager disagree; the message says how to recover."""


# Any: StripeClient's v1 services are dynamically typed objects; the fake in the tests mirrors
# only the calls used here (list and create with params/options dicts).
Client = Any


def lookup_key(cfg: StripeSetup) -> str:
    return f"reel-{cfg.currency}-{cfg.unit_amount_minor}"


def check_mode(key: SecretStr, mode: str) -> None:
    if not key.get_secret_value().startswith(KEY_PREFIXES.get(mode, ())):
        raise ValueError(f"STRIPE_SECRET_KEY is not a {mode} mode key")


def webhook_url(
    runner: Runner, project: str, region: str, cfg: StripeSetup, timeout_s: float
) -> str:
    """The service URL is known before the service exists (F61)."""
    out = runner(
        ["gcloud", "projects", "describe", project, "--format=value(projectNumber)"],
        None,
        timeout_s,
    )
    return service_url(out.strip(), region) + cfg.webhook_path


def ensure_price(client: Client, cfg: StripeSetup) -> str:
    key = lookup_key(cfg)
    found = client.v1.prices.list(params={"lookup_keys": [key], "limit": 1}).data
    if found:
        say(f"stripe-setup: price {key} exists")
        return str(found[0].id)
    product = client.v1.products.create(
        params={"name": cfg.product_name}, options={"idempotency_key": f"product-{key}"}
    )
    price = client.v1.prices.create(
        params={
            "currency": cfg.currency,
            "unit_amount": cfg.unit_amount_minor,
            "product": product.id,
            "lookup_key": key,
        },
        options={"idempotency_key": f"price-{key}"},
    )
    say(f"stripe-setup: price {key} created")
    return str(price.id)


def ensure_webhook(client: Client, url: str, cfg: StripeSetup, store: SecretStore) -> bool:
    """True when a new endpoint was created and its secret stored.

    The signing secret is shown only at creation, so the container must exist first, and an
    existing endpoint without a stored secret stops the run instead of reporting success.
    """
    existing = [
        e for e in client.v1.webhook_endpoints.list(params={"limit": 100}).data if e.url == url
    ]
    if existing:
        if not store.has_value(WEBHOOK_SECRET_ID):
            raise SetupError(
                f"webhook endpoint {existing[0].id} exists but {WEBHOOK_SECRET_ID} holds no value;"
                " delete that endpoint in the Stripe dashboard and run make stripe-setup again"
            )
        say("stripe-setup: webhook endpoint exists and its secret is stored")
        return False
    store.ready(WEBHOOK_SECRET_ID)
    endpoint = client.v1.webhook_endpoints.create(
        params={"url": url, "enabled_events": cfg.events, "api_version": STRIPE_API_VERSION}
    )
    store.put(WEBHOOK_SECRET_ID, SecretStr(endpoint.secret))
    say("stripe-setup: webhook endpoint created, signing secret stored")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stripe product, price and cloud webhook.")
    parser.add_argument("--mode", choices=sorted(KEY_PREFIXES), required=True)
    mode = parser.parse_args(argv).mode
    cloud_settings = CloudSettings()
    key = WebSettings().stripe_secret_key
    cfg = load_cloud()
    try:
        if key is None:
            raise ValueError("STRIPE_SECRET_KEY is not set in .env")
        check_mode(key, mode)
        client = stripe.StripeClient(
            key.get_secret_value(),
            stripe_version=STRIPE_API_VERSION,
            max_network_retries=cfg.stripe.max_network_retries,
            http_client=stripe.RequestsClient(timeout=cfg.stripe.timeout_s),
        )
        timeout_s = cfg.gcloud.timeout_s
        url = webhook_url(
            run, cloud_settings.gcp_project, cloud_settings.gcp_region, cfg.stripe, timeout_s
        )
        ensure_price(client, cfg.stripe)
        store = GcloudSecrets(run, cloud_settings.gcp_project, timeout_s)
        ensure_webhook(client, url, cfg.stripe, store)
    except (ValueError, CommandError, SetupError, stripe.StripeError) as exc:
        say(f"stripe-setup: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
