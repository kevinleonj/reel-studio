"""REVIEW-FIXES WEB 3: an address no mail header accepts never reaches the mailer."""

from email.errors import HeaderParseError
from email.message import EmailMessage

import pytest

from reel_studio.adapters.mailer_smtp import SmtpMailer
from reel_studio.core.errors import DeliveryFailed
from reel_studio.core.mail_address import header_accepts
from tests.unit.api.conftest import Api
from tests.unit.api.test_api_orders import SETTINGS
from tests.unit.api.test_api_pins import LINK_DATA

CRAFTED = "=?utf-8?q?x=0Ay?=@b.c"  # passes EMAIL_SHAPE, decodes to a header with a line break
# More shapes that pass EMAIL_SHAPE but break the header parser (review round 1: AttributeError
# and IndexError on Python 3.13.12, accepted on 3.13.16).
BROKEN = [CRAFTED, "g:;@b.co", "=?utf-8?b?@b.co", '"@b.co']


@pytest.mark.parametrize("address", BROKEN)
def test_an_address_no_mail_header_accepts_is_refused_before_the_order(
    api: Api, address: str
) -> None:
    if header_accepts(address):
        pytest.skip("this Python's email package accepts it")
    response = api.client.post(
        "/api/checkout",
        json={"settings": SETTINGS, "code": "", "email": address},
    )
    assert (response.status_code, response.json()) == (422, {"error": "invalid_request"})
    assert api.orders.orders == {}


@pytest.mark.parametrize("address", BROKEN)
def test_the_mailer_turns_an_unusable_address_into_a_delivery_failure(address: str) -> None:
    if header_accepts(address):
        pytest.skip("this Python's email package accepts it")
    mailer = SmtpMailer("127.0.0.1", 1, sender="r@example.test", timeout_s=1.0)
    with pytest.raises(DeliveryFailed):
        mailer.send("link", address, LINK_DATA)


# Listed here, not taken from HEADER_ERRORS: dropping a member must fail its own case.
PARSER_ERRORS = (ValueError, HeaderParseError, AttributeError, IndexError, TypeError)


@pytest.mark.parametrize("error", PARSER_ERRORS)
def test_every_header_error_refuses_the_address_and_fails_the_delivery(
    monkeypatch: pytest.MonkeyPatch, api: Api, error: type[Exception]
) -> None:
    """The stdlib bug behind each member exists only on some patch releases; pin all of them."""
    real = EmailMessage.__setitem__

    def broken(self: EmailMessage, name: str, value: object) -> None:
        if name == "To":
            raise error("broken header")
        real(self, name, value)

    monkeypatch.setattr(EmailMessage, "__setitem__", broken)
    assert header_accepts("ana@example.test") is False
    response = api.client.post(
        "/api/checkout", json={"settings": SETTINGS, "code": "", "email": "ana@example.test"}
    )
    assert response.status_code == 422
    mailer = SmtpMailer("127.0.0.1", 1, sender="r@example.test", timeout_s=1.0)
    with pytest.raises(DeliveryFailed):
        mailer.send("link", "ana@example.test", LINK_DATA)
