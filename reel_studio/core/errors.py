"""Typed exceptions per boundary and the user-message keys (docs/EDITOR.md §10, UX.md).

Every exception carries a stable `code`. The order document stores it (`error.code`) and the
website shows the message for that key from the one copy table (web/src/copy/en.json). Message
text never lives here.
"""

from enum import StrEnum
from typing import ClassVar


class ErrorCode(StrEnum):
    """Keys of the user-message table. `cost_cap` is named in EDITOR.md; the rest follow it."""

    # editor job (EDITOR.md §10)
    NO_USABLE_INPUT = "no_usable_input"
    MODEL_REFUSAL = "model_refusal"
    COST_CAP = "cost_cap"
    OUTPUT_TOO_LONG = "output_too_long"
    SPEND_LIMIT = "spend_limit"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    RENDER_ERROR = "render_error"
    JOB_KILLED = "job_killed"  # set by the sweep when a lease expires; no exception
    # website API (ARCHITECTURE.md §6, UX.md)
    CODE_INVALID = "code_invalid"
    CODE_INACTIVE = "code_inactive"
    WEEK_FULL = "week_full"
    RATE_LIMITED = "rate_limited"
    TOO_MANY_FILES = "too_many_files"
    TOO_LARGE = "too_large"
    BAD_TYPE = "bad_type"
    NO_FILES = "no_files"


class ReelError(Exception):
    """Base of every error the product raises on purpose."""

    code: ClassVar[ErrorCode]


# ---------------------------------------------------------------- boundaries


class InputError(ReelError):
    """The user's files cannot be used (prepare)."""


class EditorError(ReelError):
    """The editing loop stopped (loop, meter)."""


class ProviderError(ReelError):
    """An outside service failed or refused after our retries (Claude, Gemini)."""


class MediaError(ReelError):
    """ffmpeg or ffprobe failed (render)."""


class ApiError(ReelError):
    """A website request was refused; the API maps each code to an HTTP status."""


BOUNDARIES: tuple[type[ReelError], ...] = (
    InputError,
    EditorError,
    ProviderError,
    MediaError,
    ApiError,
)

# ---------------------------------------------------------------- editor job


class NoUsableInput(InputError):
    code = ErrorCode.NO_USABLE_INPUT


class ModelRefusal(EditorError):
    code = ErrorCode.MODEL_REFUSAL


class CostCapReached(EditorError):
    code = ErrorCode.COST_CAP


class OutputTooLong(EditorError):
    code = ErrorCode.OUTPUT_TOO_LONG


class SpendLimitReached(ProviderError):
    code = ErrorCode.SPEND_LIMIT


class ProviderUnavailable(ProviderError):
    code = ErrorCode.PROVIDER_UNAVAILABLE


class RenderError(MediaError):
    code = ErrorCode.RENDER_ERROR


# ---------------------------------------------------------------- website API


class CodeInvalid(ApiError):
    code = ErrorCode.CODE_INVALID


class CodeInactive(ApiError):
    code = ErrorCode.CODE_INACTIVE


class WeekFull(ApiError):
    code = ErrorCode.WEEK_FULL


class RateLimited(ApiError):
    code = ErrorCode.RATE_LIMITED


class TooManyFiles(ApiError):
    code = ErrorCode.TOO_MANY_FILES


class TooLarge(ApiError):
    code = ErrorCode.TOO_LARGE


class BadType(ApiError):
    code = ErrorCode.BAD_TYPE


class NoFiles(ApiError):
    code = ErrorCode.NO_FILES
