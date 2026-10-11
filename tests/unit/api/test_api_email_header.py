"""REVIEW-FIXES WEB 3: an address no mail header accepts never reaches the mailer."""

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
