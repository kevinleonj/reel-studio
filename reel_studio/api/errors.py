"""Errors the API answers with, as {"error": "<code>"} and one status per code.

User-facing codes come from reel_studio/core/errors.py (their words live in web/src/copy/en.json);
the rest are protocol answers the page treats as "couldn't reach the server".
"""

from http import HTTPStatus

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from reel_studio.core.errors import ApiError, BadType, ErrorCode
from reel_studio.core.logging import get_logger

log = get_logger(__name__)

STATUS: dict[ErrorCode, HTTPStatus] = {
    ErrorCode.CODE_INVALID: HTTPStatus.BAD_REQUEST,
    ErrorCode.CODE_INACTIVE: HTTPStatus.BAD_REQUEST,
    ErrorCode.WEEK_FULL: HTTPStatus.CONFLICT,
    ErrorCode.RATE_LIMITED: HTTPStatus.TOO_MANY_REQUESTS,
    ErrorCode.TOO_MANY_FILES: HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    ErrorCode.TOO_LARGE: HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    ErrorCode.BAD_TYPE: HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
    ErrorCode.NO_FILES: HTTPStatus.CONFLICT,
}


class Refused(Exception):
    """A protocol refusal with a fixed code and status (not a user-message key)."""

    def __init__(self, code: str, status: HTTPStatus) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def not_found() -> Refused:
    """Same answer for a wrong id, a wrong token and a missing token (ARCHITECTURE.md §7)."""
    return Refused("not_found", HTTPStatus.NOT_FOUND)


def wrong_status() -> Refused:
    return Refused("wrong_status", HTTPStatus.CONFLICT)


def invalid(reason: str) -> Refused:
    log.info(
        "request refused: %s", reason, extra={"event": "invalid_request", "outcome": "refused"}
    )
    return Refused("invalid_request", HTTPStatus.UNPROCESSABLE_ENTITY)


async def on_api_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):  # registered for ApiError only
        raise TypeError(exc)
    body: dict[str, str] = {"error": str(exc.code)}
    if isinstance(exc, BadType) and exc.args:
        body["file"] = str(exc.args[0])
    return JSONResponse(body, status_code=STATUS[exc.code])


async def on_refused(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, Refused):  # registered for Refused only
        raise TypeError(exc)
    return JSONResponse({"error": exc.code}, status_code=exc.status)


async def on_validation(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):  # registered for RequestValidationError only
        raise TypeError(exc)
    # Field locations only: the values may be what the user typed.
    log.info(
        "request body refused",
        extra={"event": "invalid_request", "outcome": str([e["loc"] for e in exc.errors()])},
    )
    return JSONResponse({"error": "invalid_request"}, status_code=HTTPStatus.UNPROCESSABLE_ENTITY)
