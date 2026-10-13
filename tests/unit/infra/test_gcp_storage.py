"""GcpStorage: the cloud Storage port over Cloud Storage (D54, F32-F34), against a fake bucket."""

import logging
from datetime import timedelta
from pathlib import Path

import google.auth
import google.auth.exceptions
import httpx
import pytest
from google.api_core import exceptions as google_exceptions

from reel_studio.adapters.gcp_storage import (
    AdcIdentity,
    GcpStorage,
    SessionCanceller,
    SigningIdentity,
    StorageConfig,
    storage_retry,
)
from reel_studio.core import config, ports
from reel_studio.core.errors import CloudUnavailable
from tests.fakes.gcp import FakeBucket

ORIGIN = "https://reel-api-123.test-region.run.app"
TIMEOUT_S = 12.0
MAX_MINUTES = 60
RETRY = object()
IDENTITY = SigningIdentity(email="reel-api@test-project.iam.gserviceaccount.com", token="tok")


def make(bucket: FakeBucket) -> GcpStorage:
    cfg = StorageConfig(
        origin=ORIGIN, timeout_s=TIMEOUT_S, retry=RETRY, signed_url_max_minutes=MAX_MINUTES
    )
    return GcpStorage(bucket, lambda: IDENTITY, cfg, cancel=bucket.cancel)


def test_satisfies_the_port() -> None:
    storage: ports.Storage = make(FakeBucket())
    assert storage is not None


def test_upload_session_is_bound_to_origin_and_size() -> None:
    bucket = FakeBucket()

    target = make(bucket).create_upload_session(
        "o1", {"name": "clip.mov", "size": 1234, "type": "video/quicktime"}
    )

    assert target["name"] == "clip.mov"
    assert str(target["upload_url"]).startswith("https://storage.test/upload/in/o1/clip.mov")
    [read, (action, key, details), write] = bucket.calls
    assert read[:2] == ("read", "work/o1/upload-sessions/clip.mov")
    assert (action, key) == ("session", "in/o1/clip.mov")
    assert details == {"size": 1234, "origin": ORIGIN, "content_type": "video/quicktime"}
    assert write[:2] == ("write", "work/o1/upload-sessions/clip.mov")
    assert bucket.contents["work/o1/upload-sessions/clip.mov"].decode() == target["upload_url"]


def test_a_failed_cancel_keeps_the_older_session_recorded_for_the_retry() -> None:
    """Open, cancel, then record (review W3): if the cancel fails, the marker still names the
    older live session, so the browser's retry cancels it."""
    bucket = FakeBucket()
    calls = {"n": 0}

    def cancel_fails_once(url: str) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise CloudUnavailable("cloud storage cancel failed: HTTP 503")
        bucket.cancel(url)

    cfg = StorageConfig(
        origin=ORIGIN, timeout_s=TIMEOUT_S, retry=RETRY, signed_url_max_minutes=MAX_MINUTES
    )
    storage = GcpStorage(bucket, lambda: IDENTITY, cfg, cancel=cancel_fails_once)
    meta = {"name": "clip.mov", "size": 3, "type": "video/quicktime"}
    first = storage.create_upload_session("o1", meta)

    with pytest.raises(CloudUnavailable):
        storage.create_upload_session("o1", meta)
    assert bucket.contents["work/o1/upload-sessions/clip.mov"].decode() == first["upload_url"]
    third = storage.create_upload_session("o1", meta)

    assert first["upload_url"] not in bucket.sessions
    assert bucket.contents["work/o1/upload-sessions/clip.mov"].decode() == third["upload_url"]


def test_asking_again_cancels_the_older_session_after_opening_the_new() -> None:
    bucket = FakeBucket()
    storage = make(bucket)
    meta = {"name": "clip.mov", "size": 3, "type": "video/quicktime"}

    first = storage.create_upload_session("o1", meta)
    second = storage.create_upload_session("o1", meta)

    assert [c[:2] for c in bucket.calls if c[0] in {"session", "cancel"}] == [
        ("session", "in/o1/clip.mov"),
        ("session", "in/o1/clip.mov"),
        ("cancel", first["upload_url"]),
    ]
    assert list(bucket.sessions) == [second["upload_url"]]


@pytest.mark.parametrize("name", ["../escape.mov", "a/b.mov", "", "."])
def test_file_names_cannot_leave_the_order_folder(name: str) -> None:
    with pytest.raises(ValueError, match="file name"):
        make(FakeBucket()).create_upload_session(
            "o1", {"name": name, "size": 1, "type": "video/mp4"}
        )


def test_list_inputs_empty_one_many() -> None:
    bucket = FakeBucket()
    storage = make(bucket)
    assert storage.list_inputs("o1") == []

    bucket.contents["in/o1/a.mov"] = b"aa"
    bucket.types["in/o1/a.mov"] = "video/quicktime"
    assert storage.list_inputs("o1") == [{"name": "a.mov", "size": 2, "key": "in/o1/a.mov"}]

    bucket.contents["in/o1/b.jpg"] = b"bbb"
    bucket.contents["in/o2/other.mov"] = b"x"
    assert [item["key"] for item in storage.list_inputs("o1")] == ["in/o1/a.mov", "in/o1/b.jpg"]


def test_download_and_upload_round_trip(tmp_path: Path) -> None:
    bucket = FakeBucket()
    storage = make(bucket)
    source = tmp_path / "reel.mp4"
    source.write_bytes(b"reel")

    storage.upload(source, "out/o1/reel.mp4", "video/mp4")
    storage.download("out/o1/reel.mp4", tmp_path / "copy.mp4")

    assert (tmp_path / "copy.mp4").read_bytes() == b"reel"
    assert ("upload", "out/o1/reel.mp4", {"content_type": "video/mp4"}) in bucket.calls


def test_signed_url_is_v4_attachment_signed_without_a_key_file() -> None:
    bucket = FakeBucket()

    url = make(bucket).signed_url("out/o1/reel.mp4", "my reel.mp4", 30)

    assert "X-Goog-Signature" in url
    [(action, key, details)] = bucket.calls
    assert (action, key) == ("sign", "out/o1/reel.mp4")
    assert details == {
        "version": "v4",
        "expiration": timedelta(minutes=30),
        "method": "GET",
        "response_disposition": 'attachment; filename="my reel.mp4"',
        "service_account_email": IDENTITY.email,
        "access_token": IDENTITY.token,
    }


@pytest.mark.parametrize("minutes", [0, MAX_MINUTES + 1])
def test_signed_url_lifetime_is_bounded(minutes: int) -> None:
    with pytest.raises(ValueError, match="minutes"):
        make(FakeBucket()).signed_url("out/o1/reel.mp4", "reel.mp4", minutes)


def test_delete_order_removes_every_prefix_and_is_safe_twice() -> None:
    bucket = FakeBucket()
    for key in ("in/o1/a.mov", "work/o1/edl.json", "out/o1/reel.mp4", "in/o2/keep.mov"):
        bucket.contents[key] = b"x"
    storage = make(bucket)

    storage.delete_order("o1")
    storage.delete_order("o1")

    assert list(bucket.contents) == ["in/o2/keep.mov"]


def test_object_gone_between_list_and_delete_is_fine() -> None:
    bucket = FakeBucket(contents={"in/o1/a.mov": b"x"}, stale={"in/o1/ghost.mov"})

    make(bucket).delete_order("o1")

    assert bucket.contents == {}
    assert ("delete", "in/o1/ghost.mov", {}) in bucket.calls


def test_api_failure_becomes_cloud_unavailable_and_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bucket = FakeBucket(raises=google_exceptions.ServiceUnavailable("down"))  # type: ignore[no-untyped-call]

    with caplog.at_level(logging.INFO), pytest.raises(CloudUnavailable, match="ServiceUnavailable"):
        make(bucket).create_upload_session(
            "o1", {"name": "a.mov", "size": 1, "content_type": "video/quicktime"}
        )

    [record] = [r for r in caplog.records if r.name.endswith("gcp_storage")]
    assert record.levelno == logging.ERROR
    assert record.__dict__["order_id"] == "o1"
    assert record.__dict__["outcome"] == "error"
    assert isinstance(record.__dict__["latency_ms"], int)


def test_signed_url_and_token_never_reach_the_log(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        make(FakeBucket()).signed_url("out/o1/reel.mp4", "reel.mp4", 30)

    text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "X-Goog-Signature" not in text
    assert IDENTITY.token not in text.replace("token=", "")


DEADLINE_S = 10.0


def test_storage_retry_follows_cloud_toml() -> None:
    gcp = config.load_cloud().gcp

    retry = storage_retry(gcp, DEADLINE_S)

    # api_core's Retry keeps its settings in private attributes and offers no getter.
    assert retry._timeout == DEADLINE_S
    assert retry._initial == gcp.retry_initial_s
    assert retry._multiplier == gcp.retry_multiplier
    assert retry._maximum == gcp.retry_max_s


class FakeCredentials:
    def __init__(self, *, valid: bool, email: str | None) -> None:
        self.valid = valid
        self.token = "fresh-token" if valid else None
        self.refreshes = 0
        if email is not None:
            self.service_account_email = email

    def refresh(self, _request: object) -> None:
        self.refreshes += 1
        self.valid = True
        self.token = "fresh-token"
        self.service_account_email = "reel-api@test-project.iam.gserviceaccount.com"


def adc(monkeypatch: pytest.MonkeyPatch, credentials: FakeCredentials) -> AdcIdentity:
    monkeypatch.setattr(google.auth, "default", lambda scopes: (credentials, "test-project"))
    return AdcIdentity()


def test_adc_identity_uses_valid_credentials_without_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials = FakeCredentials(valid=True, email="reel-api@test-project.iam.gserviceaccount.com")

    identity = adc(monkeypatch, credentials)()

    assert identity == SigningIdentity(
        email="reel-api@test-project.iam.gserviceaccount.com", token="fresh-token"
    )
    assert credentials.refreshes == 0


def test_adc_identity_refreshes_first_so_the_email_is_real(monkeypatch: pytest.MonkeyPatch) -> None:
    credentials = FakeCredentials(valid=False, email="default")

    identity = adc(monkeypatch, credentials)()

    assert credentials.refreshes == 1
    assert identity.email != "default"


def test_adc_identity_refuses_a_user_login(monkeypatch: pytest.MonkeyPatch) -> None:
    credentials = FakeCredentials(valid=True, email=None)

    with pytest.raises(CloudUnavailable, match="service-account"):
        adc(monkeypatch, credentials)()


@pytest.mark.parametrize(
    "error",
    [
        google_exceptions.RetryError("deadline", cause=None),  # type: ignore[no-untyped-call]
        google.auth.exceptions.TransportError("signBlob refused"),  # type: ignore[no-untyped-call]
        google.auth.exceptions.RefreshError("token"),  # type: ignore[no-untyped-call]
    ],
    ids=["retry-deadline", "signblob-transport", "refresh"],
)
def test_retry_and_auth_failures_are_typed_too(error: Exception) -> None:
    def failing_identity() -> SigningIdentity:
        raise error

    cfg = StorageConfig(ORIGIN, TIMEOUT_S, RETRY, MAX_MINUTES)
    bucket = FakeBucket()
    storage = GcpStorage(bucket, failing_identity, cfg, cancel=bucket.cancel)

    with pytest.raises(CloudUnavailable) as caught:
        storage.signed_url("out/o1/reel.mp4", "reel.mp4", 30)

    assert type(error).__name__ in str(caught.value)


SESSION_URL = "https://storage.test/upload/in/o1/a.mov?upload_id=1"


def canceller(status: int, seen: list[httpx.Request]) -> SessionCanceller:
    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status)

    return SessionCanceller(httpx.Client(transport=httpx.MockTransport(answer)))


@pytest.mark.parametrize("status", [499, 404, 410, 200, 400, 401, 403])
def test_a_cancelled_or_finished_session_counts_as_closed(status: int) -> None:
    seen: list[httpx.Request] = []

    canceller(status, seen)(SESSION_URL)

    [request] = seen
    assert (request.method, str(request.url)) == ("DELETE", SESSION_URL)
    assert request.headers["Content-Length"] == "0"
    assert "Authorization" not in request.headers  # the session URL is its own credential


@pytest.mark.parametrize("status", [500, 503, 408, 429])
def test_a_session_that_may_still_be_open_is_cloud_unavailable(status: int) -> None:
    with pytest.raises(CloudUnavailable, match=f"HTTP {status}"):
        canceller(status, [])(SESSION_URL)


def test_a_cancel_that_never_arrives_is_cloud_unavailable_without_the_url(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    cancel = SessionCanceller(httpx.Client(transport=httpx.MockTransport(broken)))
    with caplog.at_level(logging.INFO), pytest.raises(CloudUnavailable) as caught:
        cancel(SESSION_URL)
    assert "upload_id" not in str(caught.value)
    assert "upload_id" not in caplog.text
