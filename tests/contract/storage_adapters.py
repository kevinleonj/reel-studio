"""Every Storage adapter the contract suite runs against, with its own way to finish an upload."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from reel_studio.adapters.storage_local import LocalStorage
from reel_studio.core.ports import Storage, UploadTarget
from tests.fakes.clock import FrozenClock
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


ADAPTERS = (StorageFactory("fake", _fake), StorageFactory("local", _local))
