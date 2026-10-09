"""Cloud adapter for the Storage port: one Cloud Storage bucket, prefixes in/ work/ out/ (D54).

- Uploads: the browser PUTs straight to a resumable session this adapter creates, bound to the
  website's origin and capped at the declared size (F32, F33); Cloud Run never carries the bytes.
- Downloads: V4 signed URLs with `Content-Disposition: attachment`, signed without a key file
  through IAM signBlob, which needs roles/iam.serviceAccountTokenCreator on reel-api (F34).
- Every call has a timeout and the bounded retry from config/cloud.toml, and logs its latency.
"""

import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import Protocol

import google.auth
from google.api_core.exceptions import GoogleAPICallError, NotFound
from google.api_core.retry import Retry
from google.auth.transport.requests import Request

# google-cloud-storage ships no py.typed; the module override belongs in pyproject.toml (main lane).
from google.cloud.storage.retry import DEFAULT_RETRY  # type: ignore[import-untyped]

from reel_studio.core import config, ports
from reel_studio.core.constants import GOOGLE_CLOUD_PLATFORM_SCOPE
from reel_studio.core.errors import CloudUnavailable
from reel_studio.core.logging import get_logger, latency_ms

log = get_logger(__name__)

# Bucket layout (D54): uploads, intermediate files, finished Reels. Lifecycle rules in
# infra/main/main.tf delete each prefix on its own schedule.
INPUT_PREFIX = "in"
WORK_PREFIX = "work"
OUTPUT_PREFIX = "out"
ORDER_PREFIXES = (INPUT_PREFIX, WORK_PREFIX, OUTPUT_PREFIX)
SIGNED_URL_VERSION = "v4"  # the default is v2 (doc ledger: google-cloud-storage)


class Blob(Protocol):
    """The slice of google.cloud.storage.Blob this adapter uses."""

    name: str
    size: int | None
    content_type: str | None

    def create_resumable_upload_session(
        self, *, content_type: str, size: int, origin: str, timeout: float, retry: object
    ) -> str: ...
    def generate_signed_url(self, **options: object) -> str: ...
    def download_to_filename(self, filename: str, *, timeout: float, retry: object) -> None: ...
    def upload_from_filename(
        self, filename: str, *, content_type: str, timeout: float, retry: object
    ) -> None: ...
    def delete(self, *, timeout: float, retry: object) -> None: ...


class Bucket(Protocol):
    def blob(self, name: str) -> Blob: ...
    def list_blobs(self, *, prefix: str, timeout: float, retry: object) -> Iterable[Blob]: ...


@dataclass(frozen=True)
class SigningIdentity:
    email: str
    token: str


IdentitySource = Callable[[], SigningIdentity]


@dataclass(frozen=True)
class StorageConfig:
    origin: str  # the website's origin: only it may complete an upload (F32)
    timeout_s: float
    retry: object  # a google.api_core Retry, from storage_retry()
    signed_url_max_minutes: int


def storage_retry(gcp: config.Gcp) -> Retry:
    """The library's retry policy with our deadline and backoff (doc ledger: google)."""
    retry: Retry = DEFAULT_RETRY.with_timeout(gcp.retry_deadline_s).with_delay(
        initial=gcp.retry_initial_s, multiplier=gcp.retry_multiplier, maximum=gcp.retry_max_s
    )
    return retry


class AdcIdentity:
    """The runtime service account's email and a fresh access token (Cloud Run metadata server).

    The email is the string 'default' until the first refresh, so refresh before reading it.
    """

    def __init__(self) -> None:
        credentials, _ = google.auth.default(scopes=[GOOGLE_CLOUD_PLATFORM_SCOPE])
        self._credentials = credentials

    def __call__(self) -> SigningIdentity:
        if not self._credentials.valid:
            self._credentials.refresh(Request())  # type: ignore[no-untyped-call]
        # Only service-account credentials carry an email; a user login cannot sign (F34).
        email = getattr(self._credentials, "service_account_email", None)
        if not isinstance(email, str) or email == "default":
            raise CloudUnavailable("signing needs service-account credentials (Cloud Run)")
        return SigningIdentity(email=email, token=str(self._credentials.token))


def input_key(order_id: str, name: str) -> str:
    if not name or PurePosixPath(name).name != name or name in {".", ".."}:
        raise ValueError(f"file name {name!r} must be a plain name without folders")
    return f"{INPUT_PREFIX}/{order_id}/{name}"


class GcpStorage:
    def __init__(self, bucket: Bucket, identity: IdentitySource, cfg: StorageConfig) -> None:
        self._bucket = bucket
        self._identity = identity
        self._cfg = cfg

    def create_upload_session(self, order_id: str, file: ports.Record) -> ports.UploadTarget:
        key = input_key(order_id, str(file["name"]))
        size = file["size"]
        if not isinstance(size, int):
            raise ValueError(f"file size must be an int, not {size!r}")
        with _Logged("upload_session", order_id):
            url = self._bucket.blob(key).create_resumable_upload_session(
                content_type=str(file["content_type"]),
                size=size,
                origin=self._cfg.origin,
                timeout=self._cfg.timeout_s,
                retry=self._cfg.retry,
            )
        return {"key": key, "url": url}

    def list_inputs(self, order_id: str) -> list[ports.Record]:
        with _Logged("list_inputs", order_id):
            blobs = list(self._list(f"{INPUT_PREFIX}/{order_id}/"))
        return [{"key": b.name, "size": b.size, "content_type": b.content_type} for b in blobs]

    def download(self, key: str, path: Path) -> None:
        with _Logged("download", None):
            self._bucket.blob(key).download_to_filename(
                str(path), timeout=self._cfg.timeout_s, retry=self._cfg.retry
            )

    def upload(self, path: Path, key: str, content_type: str) -> None:
        with _Logged("upload", None):
            self._bucket.blob(key).upload_from_filename(
                str(path),
                content_type=content_type,
                timeout=self._cfg.timeout_s,
                retry=self._cfg.retry,
            )

    def signed_url(self, key: str, filename: str, minutes: int) -> str:
        if not 0 < minutes <= self._cfg.signed_url_max_minutes:
            raise ValueError(
                f"signed URL minutes must be 1 to {self._cfg.signed_url_max_minutes}, not {minutes}"
            )
        identity = self._identity()
        with _Logged("sign", None):
            return self._bucket.blob(key).generate_signed_url(
                version=SIGNED_URL_VERSION,
                expiration=timedelta(minutes=minutes),
                method="GET",
                response_disposition=f'attachment; filename="{filename}"',
                service_account_email=identity.email,
                access_token=identity.token,
            )

    def delete_order(self, order_id: str) -> None:
        """Every object of the order; safe to call twice (an object already gone is fine)."""
        with _Logged("delete_order", order_id):
            for prefix in ORDER_PREFIXES:
                for blob in list(self._list(f"{prefix}/{order_id}/")):
                    try:
                        self._bucket.blob(blob.name).delete(
                            timeout=self._cfg.timeout_s, retry=self._cfg.retry
                        )
                    except NotFound:
                        continue  # deleted between list and delete: the goal is already met

    def _list(self, prefix: str) -> Iterator[Blob]:
        yield from self._bucket.list_blobs(
            prefix=prefix, timeout=self._cfg.timeout_s, retry=self._cfg.retry
        )


class _Logged:
    """Logs one storage call with its latency; turns an API failure into CloudUnavailable."""

    def __init__(self, event: str, order_id: str | None) -> None:
        self._event = event
        self._order_id = order_id
        self._started = time.monotonic()

    def __enter__(self) -> None:
        self._started = time.monotonic()

    def __exit__(
        self, kind: type[BaseException] | None, exc: BaseException | None, _tb: object
    ) -> None:
        outcome = "ok" if exc is None else "error"
        fields = {
            "order_id": self._order_id,
            "stage": "storage",
            "event": self._event,
            "latency_ms": latency_ms(self._started),
            "outcome": outcome,
        }
        if exc is None:
            log.info("storage %s", self._event, extra=fields)
            return
        log.error("storage %s failed error=%s", self._event, type(exc).__name__, extra=fields)
        if isinstance(exc, GoogleAPICallError):
            raise CloudUnavailable(f"cloud storage {self._event} failed: {exc}") from exc
