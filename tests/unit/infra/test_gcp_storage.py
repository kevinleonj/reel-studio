"""GcpStorage: the cloud Storage port over Cloud Storage (D54, F32-F34), against a fake bucket."""

import logging
from datetime import timedelta
from pathlib import Path

import google.auth
import google.auth.exceptions
import pytest
from google.api_core import exceptions as google_exceptions

from reel_studio.adapters.gcp_storage import (
    AdcIdentity,
    GcpStorage,
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
    return GcpStorage(bucket, lambda: IDENTITY, cfg)


def test_satisfies_the_port() -> None:
    storage: ports.Storage = make(FakeBucket())
    assert storage is not None


def test_upload_session_is_bound_to_origin_and_size() -> None:
    bucket = FakeBucket()

    target = make(bucket).create_upload_session(
        "o1", {"name": "clip.mov", "size": 1234, "content_type": "video/quicktime"}
    )

    assert target["key"] == "in/o1/clip.mov"
    assert str(target["url"]).startswith("https://storage.test/upload/in/o1/clip.mov")
    [(action, key, details)] = bucket.calls
    assert (action, key) == ("session", "in/o1/clip.mov")
    assert details == {"size": 1234, "origin": ORIGIN, "content_type": "video/quicktime"}


@pytest.mark.parametrize("name", ["../escape.mov", "a/b.mov", "", "."])
def test_file_names_cannot_leave_the_order_folder(name: str) -> None:
    with pytest.raises(ValueError, match="file name"):
        make(FakeBucket()).create_upload_session(
            "o1", {"name": name, "size": 1, "content_type": "video/mp4"}
        )


def test_list_inputs_empty_one_many() -> None:
    bucket = FakeBucket()
    storage = make(bucket)
    assert storage.list_inputs("o1") == []

    bucket.contents["in/o1/a.mov"] = b"aa"
    bucket.types["in/o1/a.mov"] = "video/quicktime"
    assert storage.list_inputs("o1") == [
        {"key": "in/o1/a.mov", "size": 2, "content_type": "video/quicktime"}
    ]

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


def test_storage_retry_follows_cloud_toml() -> None:
    gcp = config.load_cloud().gcp

    retry = storage_retry(gcp)

    # api_core's Retry keeps its settings in private attributes and offers no getter.
    assert retry._timeout == gcp.retry_deadline_s
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
    storage = GcpStorage(FakeBucket(), failing_identity, cfg)

    with pytest.raises(CloudUnavailable) as caught:
        storage.signed_url("out/o1/reel.mp4", "reel.mp4", 30)

    assert type(error).__name__ in str(caught.value)
