"""PAYMENTS=stripe: checkout with a promotion code, the webhook, /fulfil, /cancel and the sweep's
Stripe check (docs/ARCHITECTURE.md §7, D22, D58), against FakePayments."""

import hashlib
import logging
import re
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from reel_studio.api.deps import ApiDeps
from reel_studio.api.payments import sweep
from reel_studio.core.errors import PaymentsFailed
from tests.fakes.payments import VALID_SIGNATURE, FakePayments
from tests.unit.api.conftest import START, Api

SETTINGS = {
    "style": "recipe",
    "length_s": 30,
    "text_lang": "en",
    "keep_voice": False,
    "chips": [],
    "note": "",
}
CODE = "FRIEND-ANA"
SITE = "http://127.0.0.1:8000"
SUCCESS = re.compile(rf"^{re.escape(SITE)}/o/(?P<id>[0-9a-f]{{32}})\?t=(?P<token>[A-Za-z0-9_-]+)$")


def pay(api: Api) -> FakePayments:
    assert api.payments is not None
    return api.payments


def deps(api: Api) -> ApiDeps:
    found: ApiDeps = api.client.app.state.deps  # type: ignore[attr-defined]
    return found


def checkout(api: Api, code: str = CODE) -> tuple[int, dict[str, object]]:
    body = {"settings": SETTINGS, "code": code, "email": ""}
    response = api.client.post("/api/checkout", json=body)
    return response.status_code, response.json()


def started(api: Api) -> tuple[str, str, str]:
    """A checkout with a good code: (order id, token, session id)."""
    pay(api).add_code(CODE, percent_off=100)
    status, body = checkout(api)
    assert status == 200, body
    created = pay(api).created[-1]
    match = SUCCESS.match(str(created["urls"]["success"]))  # type: ignore[index]
    assert match is not None
    session_id = str(body["checkout_url"]).rsplit("/", 1)[-1]
    return match["id"], match["token"], session_id


def webhook(api: Api, kind: str, session_id: str, signature: str = VALID_SIGNATURE) -> int:
    response = api.client.post(
        "/api/stripe/webhook",
        content=pay(api).event(kind, session_id),
        headers={"Stripe-Signature": signature},
    )
    return response.status_code


def status_of(api: Api, order_id: str) -> object:
    doc = api.orders.get(order_id)
    assert doc is not None
    return doc["status"]


def held(api: Api) -> object:
    week = next(iter(api.orders.weeks.values()), None)
    return week["count"] if week is not None else 0


# ---------------------------------------------------------------- checkout


def test_a_full_discount_code_opens_a_checkout_for_a_new_order(stripe_api: Api) -> None:
    order_id, token, session_id = started(stripe_api)
    doc = stripe_api.orders.get(order_id)
    assert doc is not None
    assert doc["status"] == "awaiting_payment"
    assert doc["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert doc["stripe"]["session_id"] == session_id  # type: ignore[index]
    created = pay(stripe_api).created[-1]
    assert created["promo_id"] == "promo_friend-ana"
    assert created["expires_at"] == START + timedelta(minutes=31)  # D58, F20
    assert created["urls"] == {
        "success": f"{SITE}/o/{order_id}?t={token}",
        "cancel": f"{SITE}/new?cancel={order_id}&t={token}",
    }
    assert held(stripe_api) == 1


@pytest.mark.parametrize(
    ("code", "percent_off", "active", "error"),
    [
        ("", None, True, "code_invalid"),
        ("NOBODY", None, True, "code_invalid"),
        (CODE, 50, True, "code_invalid"),  # D58: below 100% off is refused, nobody is charged
        (CODE, None, True, "code_invalid"),  # an amount-off coupon
        (CODE, 100, False, "code_inactive"),
    ],
)
def test_codes_that_could_charge_or_do_not_work_are_refused(
    stripe_api: Api, code: str, percent_off: float | None, active: bool, error: str
) -> None:
    if code == CODE:
        pay(stripe_api).add_code(CODE, percent_off=percent_off, active=active)  # type: ignore[arg-type]
    assert checkout(stripe_api, code) == (400, {"error": error})
    assert stripe_api.orders.orders == {}
    assert pay(stripe_api).created == []


def test_the_code_is_matched_without_regard_to_case(stripe_api: Api) -> None:
    pay(stripe_api).add_code(CODE, percent_off=100)
    assert checkout(stripe_api, CODE.lower())[0] == 200


def test_a_full_week_refuses_before_stripe_is_called(stripe_api: Api) -> None:
    pay(stripe_api).add_code(CODE, percent_off=100)
    for _ in range(3):  # LIMITS.weekly_cap in the test config
        assert checkout(stripe_api)[0] == 200
    assert checkout(stripe_api) == (409, {"error": "week_full"})
    assert len(pay(stripe_api).created) == 3


def test_stripe_failing_gives_the_place_back(stripe_api: Api) -> None:
    pay(stripe_api).add_code(CODE, percent_off=100)
    pay(stripe_api).fail_next_checkout = True
    assert checkout(stripe_api) == (502, {"error": "payments_unavailable"})
    (doc,) = stripe_api.orders.orders.values()
    assert doc["status"] == "expired"
    assert held(stripe_api) == 0


# ---------------------------------------------------------------- webhook and /fulfil


def test_a_bad_signature_is_refused_and_changes_nothing(stripe_api: Api) -> None:
    order_id, _, session_id = started(stripe_api)
    pay(stripe_api).complete(session_id, "ana@example.test")
    assert webhook(stripe_api, "checkout.session.completed", session_id, "forged") == 400
    assert status_of(stripe_api, order_id) == "awaiting_payment"


def test_the_completed_webhook_pays_and_sends_one_link_email(stripe_api: Api) -> None:
    order_id, token, session_id = started(stripe_api)
    pay(stripe_api).complete(session_id, "ana@example.test")
    for _ in range(3):  # Stripe may deliver the same event more than once (F23)
        assert webhook(stripe_api, "checkout.session.completed", session_id) == 200
    doc = stripe_api.orders.get(order_id)
    assert doc is not None
    assert doc["status"] == "paid"
    assert doc["email"] == "ana@example.test"
    (mail,) = stripe_api.mailer.sent
    assert (mail.template, mail.to) == ("link", "ana@example.test")
    assert mail.data["order_url"] == f"{SITE}/o/{order_id}#t={token}"  # behind #, never ?t=


def test_a_completed_event_for_an_open_session_is_not_believed(stripe_api: Api) -> None:
    """Fulfilment re-reads the session from Stripe (ARCHITECTURE.md §9, forged webhook)."""
    order_id, _, session_id = started(stripe_api)
    assert webhook(stripe_api, "checkout.session.completed", session_id) == 200
    assert status_of(stripe_api, order_id) == "awaiting_payment"
    assert stripe_api.mailer.sent == []


def test_the_expired_webhook_gives_the_place_back(stripe_api: Api) -> None:
    order_id, _, session_id = started(stripe_api)
    pay(stripe_api).expire_session(session_id)
    assert webhook(stripe_api, "checkout.session.expired", session_id) == 200
    assert webhook(stripe_api, "checkout.session.expired", session_id) == 200
    assert status_of(stripe_api, order_id) == "expired"
    assert held(stripe_api) == 0


def test_other_events_are_acknowledged_and_ignored(stripe_api: Api) -> None:
    order_id, _, session_id = started(stripe_api)
    assert webhook(stripe_api, "checkout.session.async_payment_failed", session_id) == 200
    assert status_of(stripe_api, order_id) == "awaiting_payment"


def test_the_success_page_fulfils_before_the_webhook(stripe_api: Api) -> None:
    order_id, token, session_id = started(stripe_api)
    auth = {"X-Order-Token": token}
    assert stripe_api.client.post(f"/api/orders/{order_id}/fulfil", headers=auth).status_code == 200
    assert status_of(stripe_api, order_id) == "awaiting_payment"  # not confirmed yet
    pay(stripe_api).complete(session_id, "ana@example.test")
    assert stripe_api.client.post(f"/api/orders/{order_id}/fulfil", headers=auth).status_code == 200
    assert status_of(stripe_api, order_id) == "paid"
    assert webhook(stripe_api, "checkout.session.completed", session_id) == 200
    assert len(stripe_api.mailer.sent) == 1


def test_fulfil_needs_the_token(stripe_api: Api) -> None:
    order_id, _, session_id = started(stripe_api)
    pay(stripe_api).complete(session_id, "ana@example.test")
    wrong = {"X-Order-Token": "not-the-token"}
    assert (
        stripe_api.client.post(f"/api/orders/{order_id}/fulfil", headers=wrong).status_code == 404
    )
    assert status_of(stripe_api, order_id) == "awaiting_payment"


def test_a_session_of_another_order_cannot_pay_this_one(stripe_api: Api) -> None:
    first, _, first_session = started(stripe_api)
    second, _, _ = started(stripe_api)
    pay(stripe_api).sessions[first_session]["order_id"] = second  # a crafted session
    pay(stripe_api).complete(first_session, "eve@example.test")
    assert webhook(stripe_api, "checkout.session.completed", first_session) == 200
    assert (status_of(stripe_api, first), status_of(stripe_api, second)) == (
        "awaiting_payment",
        "awaiting_payment",
    )


# ---------------------------------------------------------------- /cancel


def test_cancel_expires_the_session_frees_the_place_and_returns_the_settings(
    stripe_api: Api,
) -> None:
    order_id, token, session_id = started(stripe_api)
    response = stripe_api.client.post(
        f"/api/orders/{order_id}/cancel", headers={"X-Order-Token": token}
    )
    assert (response.status_code, response.json()) == (200, {"settings": SETTINGS})
    assert pay(stripe_api).expired == [session_id]
    assert status_of(stripe_api, order_id) == "expired"
    assert held(stripe_api) == 0
    again = stripe_api.client.post(
        f"/api/orders/{order_id}/cancel", headers={"X-Order-Token": token}
    )
    assert (again.status_code, again.json()) == (200, {"settings": SETTINGS})


def test_cancel_after_paying_keeps_the_order(stripe_api: Api) -> None:
    order_id, token, session_id = started(stripe_api)
    pay(stripe_api).complete(session_id, "ana@example.test")
    response = stripe_api.client.post(
        f"/api/orders/{order_id}/cancel", headers={"X-Order-Token": token}
    )
    assert (response.status_code, response.json()) == (409, {"error": "wrong_status"})
    assert status_of(stripe_api, order_id) == "paid"  # Stripe said complete: fulfilled instead


# ---------------------------------------------------------------- the sweep's Stripe check


def test_the_sweep_fulfils_a_missed_webhook_and_expires_the_rest(stripe_api: Api) -> None:
    paid_id, _, paid_session = started(stripe_api)
    open_id, _, _ = started(stripe_api)
    pay(stripe_api).complete(paid_session, "ana@example.test")
    stripe_api.clock.advance(timedelta(minutes=36))  # 31 + the 5-minute grace
    report = sweep(deps(stripe_api))
    assert status_of(stripe_api, paid_id) == "paid"
    assert status_of(stripe_api, open_id) == "expired"
    assert report["expired"] == [open_id]
    assert held(stripe_api) == 1
    assert len(stripe_api.mailer.sent) == 1


def test_the_sweep_keeps_a_checkout_it_could_not_check(stripe_api: Api) -> None:
    order_id, _, session_id = started(stripe_api)
    del pay(stripe_api).sessions[session_id]  # Stripe answers an error for this one
    stripe_api.clock.advance(timedelta(minutes=36))
    assert sweep(deps(stripe_api))["expired"] == []
    assert status_of(stripe_api, order_id) == "awaiting_payment"


def test_the_sweep_route_runs_the_stripe_check(stripe_api: Api) -> None:
    order_id, _, _ = started(stripe_api)
    stripe_api.clock.advance(timedelta(minutes=36))
    app_deps = deps(stripe_api)
    object.__setattr__(app_deps, "sweep_auth", lambda _: True)
    response = stripe_api.client.post("/api/internal/sweep")
    assert response.json()["expired"] == [order_id]


def test_the_success_url_token_is_query_only(stripe_api: Api) -> None:
    order_id, token, _ = started(stripe_api)
    success = str(pay(stripe_api).created[-1]["urls"]["success"])  # type: ignore[index]
    assert parse_qs(urlsplit(success).query) == {"t": [token]}
    assert order_id in urlsplit(success).path


def test_config_carries_the_price_with_stripe(stripe_api: Api, api: Api) -> None:
    """D58: €19, shown as the anchor and sent as the purchase value (UX.md §2)."""
    assert stripe_api.client.get("/api/config").json()["price"] == {"value": 19, "currency": "EUR"}
    assert api.client.get("/api/config").json()["price"] is None


# ---------------------------------------------------------------- senior review round 1


def test_one_bad_checkout_does_not_stop_the_sweep(stripe_api: Api) -> None:
    """W1: dead leases are freed first, and an error on one checkout leaves the next one."""
    bad, _, bad_session = started(stripe_api)
    good, _, _ = started(stripe_api)
    pay(stripe_api).complete(bad_session, "ana@example.test")
    pay(stripe_api).sessions[bad_session]["success_url"] = None  # a shape the code cannot use
    real_mark_paid = stripe_api.orders.mark_paid

    def broken(order_id: str, stripe: object) -> None:
        if order_id == bad:
            raise RuntimeError("unexpected session shape")
        real_mark_paid(order_id, stripe)  # type: ignore[arg-type]

    stripe_api.orders.mark_paid = broken  # type: ignore[method-assign]
    stripe_api.clock.advance(timedelta(minutes=36))
    report = sweep(deps(stripe_api))
    assert report["expired"] == [good]
    assert status_of(stripe_api, bad) == "awaiting_payment"  # kept for the next sweep


def test_events_without_a_session_are_acknowledged(stripe_api: Api) -> None:
    """W2: `stripe listen` forwards every event type; only two carry a session."""
    response = stripe_api.client.post(
        "/api/stripe/webhook",
        content=b'{"type": "price.created"}',
        headers={"Stripe-Signature": VALID_SIGNATURE},
    )
    assert response.status_code == 200


def test_a_complete_but_unpaid_session_does_not_pay(stripe_api: Api) -> None:
    order_id, _, session_id = started(stripe_api)
    pay(stripe_api).complete(session_id, "ana@example.test")
    pay(stripe_api).sessions[session_id]["payment_status"] = "unpaid"
    assert webhook(stripe_api, "checkout.session.completed", session_id) == 200
    assert status_of(stripe_api, order_id) == "awaiting_payment"


@pytest.mark.parametrize("route", ["webhook", "fulfil", "cancel"])
def test_stripe_unreachable_answers_502_and_changes_nothing(stripe_api: Api, route: str) -> None:
    order_id, token, session_id = started(stripe_api)
    event = pay(stripe_api).event("checkout.session.completed", session_id)
    del pay(stripe_api).sessions[session_id]  # get_session raises PaymentsFailed
    if route == "webhook":
        response = stripe_api.client.post(
            "/api/stripe/webhook", content=event, headers={"Stripe-Signature": VALID_SIGNATURE}
        )
    else:
        response = stripe_api.client.post(
            f"/api/orders/{order_id}/{route}", headers={"X-Order-Token": token}
        )
    assert (response.status_code, response.json()) == (502, {"error": "payments_unavailable"})
    assert status_of(stripe_api, order_id) == "awaiting_payment"
    assert held(stripe_api) == 1


def test_a_code_lookup_failure_answers_502_without_an_order(stripe_api: Api) -> None:
    def down(code: str) -> None:
        raise PaymentsFailed("stripe unavailable")

    pay(stripe_api).find_code = down  # type: ignore[method-assign]
    assert checkout(stripe_api) == (502, {"error": "payments_unavailable"})
    assert stripe_api.orders.orders == {}


def test_no_link_email_when_the_success_url_token_is_not_the_orders(stripe_api: Api) -> None:
    order_id, _, session_id = started(stripe_api)
    pay(stripe_api).complete(session_id, "ana@example.test")
    pay(stripe_api).sessions[session_id]["success_url"] = f"{SITE}/o/{order_id}?t=forged"
    assert webhook(stripe_api, "checkout.session.completed", session_id) == 200
    assert status_of(stripe_api, order_id) == "paid"
    assert stripe_api.mailer.sent == []


def test_no_link_email_for_an_order_that_already_expired(
    stripe_api: Api, caplog: pytest.LogCaptureFixture
) -> None:
    order_id, _, session_id = started(stripe_api)
    stripe_api.orders.expire(order_id)
    pay(stripe_api).complete(session_id, "ana@example.test")
    with caplog.at_level(logging.ERROR):
        assert webhook(stripe_api, "checkout.session.completed", session_id) == 200
    assert status_of(stripe_api, order_id) == "expired"
    assert stripe_api.mailer.sent == []
    assert "stripe completed a checkout whose order had expired" in caplog.messages


def test_the_webhook_is_absent_when_payments_are_off(api: Api) -> None:
    response = api.client.post("/api/stripe/webhook", content=b"{}")
    assert response.status_code == 404


def test_cancel_of_a_running_order_is_refused(stripe_api: Api) -> None:
    order_id, token, session_id = started(stripe_api)
    pay(stripe_api).complete(session_id, "ana@example.test")
    assert webhook(stripe_api, "checkout.session.completed", session_id) == 200
    stripe_api.orders.set_manifest(order_id, files=[], bytes_declared=0)
    stripe_api.orders.queue(order_id)
    response = stripe_api.client.post(
        f"/api/orders/{order_id}/cancel", headers={"X-Order-Token": token}
    )
    assert (response.status_code, response.json()) == (409, {"error": "wrong_status"})
    assert status_of(stripe_api, order_id) == "queued"


# ---------------------------------------------------------------- senior review round 2


def test_a_failing_stripe_phase_keeps_the_local_sweep_report(stripe_api: Api) -> None:
    """R2-W1: dead leases are failed first and stay in the report (their failure notices
    depend on it) even when listing the checkouts to check fails."""
    order_id, _, session_id = started(stripe_api)
    pay(stripe_api).complete(session_id, "ana@example.test")
    assert webhook(stripe_api, "checkout.session.completed", session_id) == 200
    stripe_api.orders.set_manifest(order_id, files=[], bytes_declared=0)
    stripe_api.orders.queue(order_id)
    assert stripe_api.orders.take_slot(order_id)
    stripe_api.clock.advance(timedelta(minutes=71))  # the 70-minute lease ran out

    def down() -> list[object]:
        raise TimeoutError("Firestore query timed out")

    stripe_api.orders.checkouts_to_check = down  # type: ignore[method-assign,assignment]
    report = sweep(deps(stripe_api))
    assert report["failed"] == [order_id]
    assert status_of(stripe_api, order_id) == "failed"
