"""Whether a mail header can carry an address. The checkout asks before any order exists, and
the mailer builds its message under the same rule, so the two never disagree (review W3)."""

from email.errors import HeaderParseError
from email.message import EmailMessage

# What the standard library's header parser raises on a malformed address. Which one depends on
# the patch release (review round 1: AttributeError and IndexError on 3.13.12, none on 3.13.16).
HEADER_ERRORS = (ValueError, HeaderParseError, AttributeError, IndexError, TypeError)


def header_accepts(address: str) -> bool:
    try:
        EmailMessage()["To"] = address
    except HEADER_ERRORS:
        return False
    return True
