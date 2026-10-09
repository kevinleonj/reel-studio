"""scripts/cloud/stripe_setup.py (`make stripe-setup MODE=test|live`), against a fake Stripe client.

Written, not run in phase A. The fake answers like StripeClient.v1 (stripe 16: `params` and
`options` dicts); the webhook's signing secret must reach Secret Manager on stdin only.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest
from pydantic import SecretStr

from reel_studio.core import config
from scripts.cloud import _shell, stripe_setup

PROJECT = "reel-studio-beta-test"
URL = "https://reel-api-123.europe-west1.run.app/api/stripe/webhook"
TIMEOUT_S = 9.0
SIGNING = "signing-value-from-stripe"


@dataclass
class Obj:
    id: str
    url: str = ""
    secret: str = ""


@dataclass
class Listing:
    data: list[Obj]


@dataclass
class Service:
    prefix: str
    existing: list[Obj] = field(default_factory=list)
    created: list[tuple[dict[str, object], dict[str, object] | None]] = field(default_factory=list)

    def list(self, params: dict[str, object] | None = None) -> Listing:
        return Listing(self.existing)

    def create(self, params: dict[str, object], options: dict[str, object] | None = None) -> Obj:
        self.created.append((params, options))
        url = str(params.get("url", ""))
        return Obj(id=f"{self.prefix}_{len(self.created)}", url=url, secret=SIGNING)


@dataclass
class V1:
    prices: Service = field(default_factory=lambda: Service("price"))
    products: Service = field(default_factory=lambda: Service("prod"))
    webhook_endpoints: Service = field(default_factory=lambda: Service("we"))


@dataclass
class FakeStripe:
    v1: V1 = field(default_factory=V1)


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(self, args: Sequence[str], stdin: str | None, timeout_s: float) -> str:
        self.calls.append((list(args), stdin))
        return "123\n" if "projects" in args else ""


def sink(runner: FakeRunner) -> _shell.SecretSink:
    return _shell.secret_sink(runner, PROJECT, TIMEOUT_S)


def cfg() -> config.StripeSetup:
    return config.load_cloud().stripe


def test_first_run_creates_product_price_and_webhook() -> None:
    client, runner = FakeStripe(), FakeRunner()

    price_id = stripe_setup.ensure_price(client, cfg())
    created = stripe_setup.ensure_webhook(client, URL, cfg(), sink(runner))

    assert price_id == "price_1"
    [(product, product_options)] = client.v1.products.created
    assert product == {"name": cfg().product_name}
    assert product_options is not None
    assert "idempotency_key" in product_options
    [(price, _)] = client.v1.prices.created
    assert price["unit_amount"] == cfg().unit_amount_minor
    assert price["currency"] == cfg().currency
    assert price["product"] == "prod_1"
    assert price["lookup_key"] == stripe_setup.lookup_key(cfg())
    assert created is True
    [(endpoint, _)] = client.v1.webhook_endpoints.created
    assert endpoint["url"] == URL
    assert endpoint["enabled_events"] == cfg().events
    assert endpoint["api_version"] == stripe_setup.STRIPE_API_VERSION
    [(args, stdin)] = runner.calls
    assert args[:5] == ["gcloud", "secrets", "versions", "add", "stripe-webhook-secret"]
    assert stdin == SIGNING
    assert SIGNING not in " ".join(args)


def test_second_run_changes_nothing() -> None:
    client, runner = FakeStripe(), FakeRunner()
    client.v1.prices.existing = [Obj(id="price_old")]
    client.v1.webhook_endpoints.existing = [Obj(id="we_old", url=URL)]

    assert stripe_setup.ensure_price(client, cfg()) == "price_old"
    assert stripe_setup.ensure_webhook(client, URL, cfg(), sink(runner)) is False
    assert client.v1.products.created == []
    assert client.v1.webhook_endpoints.created == []
    assert runner.calls == []


@pytest.mark.parametrize(
    ("prefixes_of", "mode", "ok"),
    [
        ("test", "test", True),
        ("live", "live", True),
        ("live", "test", False),
        ("test", "live", False),
    ],
)
def test_key_must_match_the_mode(prefixes_of: str, mode: str, ok: bool) -> None:
    for prefix in stripe_setup.KEY_PREFIXES[prefixes_of]:
        key = SecretStr(prefix + "x")
        if ok:
            stripe_setup.check_mode(key, mode)
        else:
            with pytest.raises(ValueError, match="mode"):
                stripe_setup.check_mode(key, mode)


def test_a_value_that_is_no_stripe_key_is_refused() -> None:
    with pytest.raises(ValueError, match="mode"):
        stripe_setup.check_mode(SecretStr("not-a-key"), "test")


def test_webhook_url_is_built_from_the_project_number() -> None:
    url = stripe_setup.webhook_url(FakeRunner(), PROJECT, "europe-west1", cfg(), TIMEOUT_S)

    assert url == URL
