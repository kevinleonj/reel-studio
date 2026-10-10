"""Order ids and link tokens (D18): the token lives only in the link; we store its SHA-256."""

import hashlib
import hmac
import re
import secrets

from reel_studio.core.constants import LINK_TOKEN_BYTES, ORDER_ID_BYTES

ORDER_ID = re.compile(r"^[0-9a-f]{32}$")


def new_order_id() -> str:
    return secrets.token_hex(ORDER_ID_BYTES)


def new_token() -> str:
    return secrets.token_urlsafe(LINK_TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_matches(token: str | None, stored_hash: object) -> bool:
    if not token or not isinstance(stored_hash, str):
        return False
    return hmac.compare_digest(hash_token(token), stored_hash)
