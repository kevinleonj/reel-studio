"""Every Storage adapter the contract suite runs against, with its own way to finish an upload."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from reel_studio.adapters.gcp_storage import GcpStorage, SigningIdentity, StorageConfig
from reel_studio.adapters.storage_local import LocalStorage
from reel_studio.core.ports import Storage, UploadTarget
from tests.fakes.clock import FrozenClock
from tests.fakes.gcp import FakeBucket
from tests.fakes.storage import FakeStorage

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


@dataclass(frozen=True)
class StorageHarness:
    storage: Storage
    complete: Callable[[UploadTarget, bytes], None]


@dataclass(frozen=True)
class StorageFactory:
    name: str
    build: Callable[[Path], StorageHarness]


def _fake(_: Path) -> StorageHarness:
    fake = FakeStorage()
    return StorageHarness(fake, fake.complete)


def _local(root: Path) -> StorageHarness:
    local = LocalStorage(
        root / "data",
        upload_path="/api/local-upload",
        download_path="/api/local-files",
        signing_key=b"k" * 32,
        clock=FrozenClock(NOW),
    )

    def complete(target: UploadTarget, data: bytes) -> None:
        session = str(target["upload_url"]).rsplit("/", 1)[1]
        local.put_chunk(session, f"bytes 0-{len(data) - 1}/{len(data)}", data)

    return StorageHarness(local, complete)


def _gcs(_: Path) -> StorageHarness:
    """GcpStorage over the fake bucket: the browser's upload is the fake's `complete`, and a
    cancelled resumable session refuses it as Cloud Storage does (a 4xx after DELETE)."""
    bucket = FakeBucket()
    cfg = StorageConfig(
        origin="https://reel-api.test", timeout_s=1.0, retry=None, signed_url_max_minutes=60
    )
    identity = SigningIdentity(email="reel-api@test.iam.gserviceaccount.com", token="t")
    storage = GcpStorage(bucket, lambda: identity, cfg, cancel=bucket.cancel)

    def complete(target: UploadTarget, data: bytes) -> None:
        bucket.complete(str(target["upload_url"]), data)

    return StorageHarness(storage, complete)


ADAPTERS = (
    StorageFactory("fake", _fake),
    StorageFactory("local", _local),
    StorageFactory("gcs", _gcs),
)
