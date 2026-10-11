"""The Stripe adapter through the real `StripeClient` and a recording HTTP client: the SDK builds
every request itself, nothing leaves the machine (STEP-07 task 1; F19-F24, F311)."""

import hashlib
import hmac
import json
import logging
import secrets
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
import stripe

from reel_studio.adapters.payments_stripe import StripePayments, StripeSetup, build_client
from reel_studio.api.main import build_payments
from reel_studio.core.config import load
from reel_studio.core.constants import STRIPE_API_VERSION
from reel_studio.core.errors import BadSignature, PaymentsFailed
from reel_studio.settings import WebSettings
from tests.conftest import MakeSettings
from tests.fakes.clock import FrozenClock

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
WEBHOOK_KEY = secrets.token_hex(16)  # made up per run: no value worth guarding
ACCOUNT = secrets.token_hex(8)  # stands in for the API key; the recorder never checks it
SETUP = StripeSetup(
    price_id="price_test_19",
    coupon_id="coupon_test_100",
    webhook_secret=WEBHOOK_KEY,
    tolerance_s=300,
)
ORDER = f"{7:032x}"
LINK_VALUE = "the-link-value"  # the order link's access value in the success URL
SUCCESS = f"http://site.test/o/{ORDER}?t={LINK_VALUE}"
JSON_TYPE = {"Content-Type": "application/json"}
Answers = Mapping[tuple[str, str], tuple[int, dict[str, Any]]]


class Recorder(stripe.HTTPClient):
    """Answers each (method, path) with a canned JSON body and records what the SDK sent."""

    name = "recorder"

    def __init__(self, answers: Answers) -> None:
        super().__init__()
        self.answers = dict(answers)
        self.sent: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str] | None,
        post_data: Any = None,
        **_: Any,
    ) -> tuple[str, int, Mapping[str, str]]:
        parts = urlsplit(url)
        raw = post_data.decode() if isinstance(post_data, bytes) else post_data or ""
        self.sent.append(
            {
                "method": method.upper(),
                "path": parts.path,
                "query": parse_qs(parts.query),
                "form": parse_qs(raw),
                "headers": dict(headers or {}),
            }
        )
        status, body = self.answers[(method.upper(), parts.path)]
        return json.dumps(body), status, JSON_TYPE

    def close(self) -> None:
        return None


def adapter(answers: Answers) -> tuple[StripePayments, Recorder]:
    recorder = Recorder(answers)
    client = stripe.StripeClient(
        ACCOUNT,
        stripe_version=STRIPE_API_VERSION,
        max_network_retries=0,
        http_client=recorder,
    )
    return StripePayments(client, FrozenClock(NOW), SETUP), recorder


def coupon(**changes: Any) -> dict[str, Any]:
    return {
        "id": SETUP.coupon_id,
        "object": "coupon",
        "percent_off": 100.0,
        "amount_off": None,
        "valid": True,
        **changes,
    }


def promo(**changes: Any) -> dict[str, Any]:
    return {
        "id": "promo_1",
        "object": "promotion_code",
        "code": "ANA-1A2B3C",
        "active": True,
        "max_redemptions": 20,
        "times_redeemed": 0,
        "expires_at": int((NOW + timedelta(days=10)).timestamp()),
        "promotion": {"type": "coupon", "coupon": coupon()},
        **changes,
    }


def listing(*items: dict[str, Any]) -> dict[str, Any]:
    return {"object": "list", "url": "/v1/promotion_codes", "has_more": False, "data": list(items)}


def session(**changes: Any) -> dict[str, Any]:
    return {
        "id": "cs_test_1",
        "object": "checkout.session",
        "url": "https://checkout.stripe.test/c/cs_test_1",
        "status": "complete",
        "payment_status": "no_payment_required",
        "client_reference_id": ORDER,
        "customer_details": {"email": "ana@example.test"},
        "success_url": SUCCESS,
        "amount_total": 0,
        **changes,
    }


LIST = ("GET", "/v1/promotion_codes")
SESSIONS = "/v1/checkout/sessions"


# ---------------------------------------------------------------- codes


def test_an_active_full_discount_code_is_found_with_its_coupon() -> None:
    payments, sent = adapter({LIST: (200, listing(promo()))})
    assert payments.find_code("ana-1a2b3c") == {
        "promo_id": "promo_1",
        "code": "ANA-1A2B3C",
        "percent_off": 100.0,
        "active": True,
    }
    (request,) = sent.sent
    assert request["query"] == {
        "code": ["ana-1a2b3c"],
        "active": ["true"],
        "expand[0]": ["data.promotion.coupon"],
        "limit": ["1"],
    }
    assert request["headers"]["Stripe-Version"] == STRIPE_API_VERSION


@pytest.mark.parametrize(
    "changes",
    [
        {"active": False},
        {"times_redeemed": 20},  # every redemption used
        {"expires_at": int(NOW.timestamp())},  # expired now
    ],
)
def test_a_code_that_cannot_be_used_is_found_but_inactive(changes: dict[str, Any]) -> None:
    payments, _ = adapter({LIST: (200, listing(promo(**changes)))})
    found = payments.find_code("ANA-1A2B3C")
    assert found is not None
    assert found["active"] is False


@pytest.mark.parametrize("changed", [{"percent_off": None, "amount_off": 500}, {"valid": False}])
def test_an_amount_off_or_invalid_coupon_has_no_percent(changed: dict[str, Any]) -> None:
    other = promo(promotion={"type": "coupon", "coupon": coupon(**changed)})
    payments, _ = adapter({LIST: (200, listing(other))})
    found = payments.find_code("X")
    assert found is not None
    assert found["percent_off"] is None


def test_an_unknown_code_is_none_after_asking_for_active_then_any() -> None:
    payments, sent = adapter({LIST: (200, listing())})
    assert payments.find_code("NOBODY") is None
    assert [r["query"].get("active") for r in sent.sent] == [["true"], None]


def test_a_code_is_created_on_the_full_discount_coupon() -> None:
    created = promo(code="ANA-ABCDEF", id="promo_9")
    payments, sent = adapter({("POST", "/v1/promotion_codes"): (200, created)})
    expires = NOW + timedelta(days=20)
    assert payments.create_code(name="Ana María", expires_at=expires, max_redemptions=20) == {
        "code": "ANA-ABCDEF",
        "promo_id": "promo_9",
    }
    form = sent.sent[0]["form"]
    assert form["promotion[type]"] == ["coupon"]
    assert form["promotion[coupon]"] == [SETUP.coupon_id]
    assert form["code"][0].startswith("ANAMARA-")
    assert form["max_redemptions"] == ["20"]
    assert form["expires_at"] == [str(int(expires.timestamp()))]


def test_expire_code_turns_the_active_code_off() -> None:
    payments, sent = adapter(
        {
            LIST: (200, listing(promo())),
            ("POST", "/v1/promotion_codes/promo_1"): (200, promo(active=False)),
        }
    )
    assert payments.expire_code("ANA-1A2B3C") is True
    assert sent.sent[-1]["form"] == {"active": ["false"]}
    nobody, _ = adapter({LIST: (200, listing())})
    assert nobody.expire_code("NOBODY") is False


# ---------------------------------------------------------------- checkout sessions


def test_the_checkout_session_carries_the_code_the_order_and_the_expiry() -> None:
    payments, sent = adapter({("POST", SESSIONS): (200, session(status="open"))})
    expires = NOW + timedelta(minutes=31)
    urls = {"success": SUCCESS, "cancel": f"http://site.test/new?cancel={ORDER}&t={LINK_VALUE}"}
    assert payments.create_checkout(ORDER, "promo_1", urls, expires) == {
        "session_id": "cs_test_1",
        "url": "https://checkout.stripe.test/c/cs_test_1",
        "amount_total": 0,
    }
    form = sent.sent[0]["form"]
    assert form["mode"] == ["payment"]
    assert form["line_items[0][price]"] == [SETUP.price_id]
    assert form["line_items[0][quantity]"] == ["1"]
    assert form["discounts[0][promotion_code]"] == ["promo_1"]
    assert form["expires_at"] == [str(int(expires.timestamp()))]
    assert form["client_reference_id"] == [ORDER]
    assert form["success_url"] == [urls["success"]]
    assert form["cancel_url"] == [urls["cancel"]]
    assert "allow_promotion_codes" not in form  # F21b


def test_a_session_is_read_back_in_the_port_shape() -> None:
    payments, _ = adapter({("GET", f"{SESSIONS}/cs_test_1"): (200, session())})
    assert payments.get_session("cs_test_1") == {
        "session_id": "cs_test_1",
        "status": "complete",
        "payment_status": "no_payment_required",
        "order_id": ORDER,
        "email": "ana@example.test",
        "success_url": SUCCESS,
    }
    unpaid = session(customer_details=None, status="open")
    open_one, _ = adapter({("GET", f"{SESSIONS}/cs_test_1"): (200, unpaid)})
    assert open_one.get_session("cs_test_1")["email"] is None


def test_expire_session_posts_to_expire() -> None:
    expired = session(status="expired")
    payments, sent = adapter({("POST", f"{SESSIONS}/cs_test_1/expire"): (200, expired)})
    payments.expire_session("cs_test_1")
    assert sent.sent[0]["path"] == f"{SESSIONS}/cs_test_1/expire"


def test_a_stripe_error_is_payments_failed_without_its_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = {
        "error": {
            "type": "invalid_request_error",
            "code": "resource_missing",
            "message": f"No such session; success_url {SUCCESS}",
        }
    }
    payments, _ = adapter({("GET", f"{SESSIONS}/cs_x"): (404, error)})
    caplog.set_level(logging.DEBUG, logger="reel_studio")
    with pytest.raises(PaymentsFailed) as raised:
        payments.get_session("cs_x")
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__
    assert LINK_VALUE not in str(raised.value)
    assert "resource_missing" in str(raised.value)
    assert all(LINK_VALUE not in record.getMessage() for record in caplog.records)


def test_an_empty_webhook_secret_is_refused_at_startup() -> None:
    client = stripe.StripeClient(ACCOUNT, http_client=Recorder({}))
    empty = StripeSetup(price_id="p", coupon_id="c", webhook_secret="", tolerance_s=300)
    with pytest.raises(ValueError, match="STRIPE_WEBHOOK_SECRET"):
        StripePayments(client, FrozenClock(NOW), empty)


# ---------------------------------------------------------------- webhooks


def signed(body: bytes, *, key: str = WEBHOOK_KEY, age_s: int = 0) -> str:
    """A `Stripe-Signature` header as Stripe builds it: HMAC-SHA256 of `t.payload` (F23)."""
    stamp = int(time.time()) - age_s  # construct_event compares with the wall clock itself
    digest = hmac.new(key.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={stamp},v1={digest}"


def event(kind: str) -> bytes:
    body = {
        "id": "evt_1",
        "object": "event",
        "type": kind,
        "api_version": STRIPE_API_VERSION,
        "created": int(NOW.timestamp()),
        "data": {"object": session()},
    }
    return json.dumps(body).encode()


@pytest.mark.parametrize("kind", ["checkout.session.completed", "checkout.session.expired"])
def test_a_signed_session_event_is_reduced_to_type_session_and_order(kind: str) -> None:
    payments, _ = adapter({})
    body = event(kind)
    assert payments.parse_webhook(body, signed(body)) == {
        "type": kind,
        "session_id": "cs_test_1",
        "order_id": ORDER,
    }


def test_other_event_types_carry_only_their_type() -> None:
    payments, _ = adapter({})
    body = event("coupon.created")
    assert payments.parse_webhook(body, signed(body)) == {"type": "coupon.created"}


@pytest.mark.parametrize("signature", ["t=1,v1=00", "", "garbage"])
def test_a_bad_signature_is_refused(signature: str) -> None:
    payments, _ = adapter({})
    with pytest.raises(BadSignature):
        payments.parse_webhook(event("checkout.session.completed"), signature)


def test_another_key_or_an_old_event_is_refused() -> None:
    payments, _ = adapter({})
    body = event("checkout.session.completed")
    with pytest.raises(BadSignature):
        payments.parse_webhook(body, signed(body, key=secrets.token_hex(16)))
    with pytest.raises(BadSignature):
        payments.parse_webhook(body, signed(body, age_s=SETUP.tolerance_s + 60))


def test_a_signed_body_that_is_not_json_is_refused() -> None:
    payments, _ = adapter({})
    body = b"not json"
    with pytest.raises(BadSignature):
        payments.parse_webhook(body, signed(body))


def test_the_client_carries_the_version_timeout_and_retries() -> None:
    client = build_client(
        ACCOUNT, api_version=STRIPE_API_VERSION, timeout_s=7, max_network_retries=3
    )
    options = client._requestor._options  # private: stripe 16.0.0 keeps them here (F321)
    assert options.stripe_version == STRIPE_API_VERSION
    assert options.max_network_retries == 3
    http = client._requestor._client
    assert isinstance(http, stripe.RequestsClient)
    assert http._timeout == 7


def test_the_composition_root_uses_the_configured_stripe_values(
    tmp_path: Path, make_settings: MakeSettings
) -> None:
    settings = make_settings(
        WebSettings,
        payments="stripe",
        stripe_secret_key="stand-in-value",
        stripe_webhook_secret="stand-in-value",
        stripe_price_id="price_test",
        stripe_coupon_id="coupon_test",
        firestore_project="p",
        smtp_host="h",
        smtp_port=1,
        data_dir=tmp_path,
        web_dist=tmp_path,
        voice_available=False,
    )
    assert isinstance(settings, WebSettings)
    times = load().limits.stripe
    built = build_payments(settings, load(), FrozenClock(NOW))
    assert built is not None
    options = built._client._requestor._options
    assert options.stripe_version == STRIPE_API_VERSION
    assert options.max_network_retries == times.max_network_retries
    http = built._client._requestor._client
    assert isinstance(http, stripe.RequestsClient)
    assert http._timeout == times.timeout_s


def test_two_codes_for_one_friend_differ() -> None:
    created = promo(code="X", id="promo_9")
    payments, sent = adapter({("POST", "/v1/promotion_codes"): (200, created)})
    later = NOW + timedelta(days=1)
    payments.create_code(name="Ana", expires_at=later, max_redemptions=1)
    payments.create_code(name="Ana", expires_at=later, max_redemptions=1)
    first, second = (r["form"]["code"][0] for r in sent.sent)
    assert first != second


def test_expire_code_looks_only_at_active_codes() -> None:
    payments, sent = adapter({LIST: (200, listing())})
    payments.expire_code("ANA-1A2B3C")
    assert [r["query"].get("active") for r in sent.sent] == [["true"]]


def test_the_setup_never_prints_the_webhook_secret() -> None:
    assert WEBHOOK_KEY not in repr(SETUP)


LIVE_PREFIXES = ("sk_" + "live_", "rk_" + "live_")  # built, so no scanner mistakes it for a key


@pytest.mark.parametrize("prefix", LIVE_PREFIXES)
def test_a_live_mode_key_is_refused_during_the_beta(
    prefix: str, tmp_path: Path, make_settings: MakeSettings
) -> None:
    """D58: the friends beta runs in Stripe test mode; live mode starts with paid orders."""
    settings = make_settings(
        WebSettings,
        payments="stripe",
        stripe_secret_key=prefix + secrets.token_hex(12),
        stripe_webhook_secret="stand-in-value",
        stripe_price_id="price_test",
        stripe_coupon_id="coupon_test",
        firestore_project="p",
        smtp_host="h",
        smtp_port=1,
        data_dir=tmp_path,
        web_dist=tmp_path,
        voice_available=False,
    )
    assert isinstance(settings, WebSettings)
    with pytest.raises(SystemExit, match="test mode"):
        build_payments(settings, load(), FrozenClock(NOW))
