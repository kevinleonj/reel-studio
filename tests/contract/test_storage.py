"""Contract for the Storage port, run against the fake and the filesystem adapter.

Uploads arrive through each adapter's own transport (Cloud Storage sessions in the cloud, the
API's chunk endpoint on the laptop), so the suite finishes an upload through `complete`, the
adapter-specific hook in tests/contract/storage_adapters.py.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from reel_studio.core.ports import Storage
from tests.contract.storage_adapters import ADAPTERS, StorageHarness

ORDER = "a" * 32
OTHER = "b" * 32


@pytest.fixture(params=[pytest.param(a, id=a.name) for a in ADAPTERS])
def harness(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[StorageHarness]:
    yield request.param.build(tmp_path)


def test_nothing_uploaded_lists_nothing(harness: StorageHarness) -> None:
    assert list(harness.storage.list_inputs(ORDER)) == []


def test_a_session_names_its_file_and_a_target(harness: StorageHarness) -> None:
    target = harness.storage.create_upload_session(
        ORDER, {"name": "a.mp4", "size": 3, "type": "video/mp4"}
    )
    assert target["name"] == "a.mp4"
    assert str(target["upload_url"])


def test_only_finished_uploads_are_listed(harness: StorageHarness) -> None:
    storage: Storage = harness.storage
    done = storage.create_upload_session(ORDER, {"name": "a.mp4", "size": 3, "type": "video/mp4"})
    storage.create_upload_session(ORDER, {"name": "b.mov", "size": 5, "type": "video/quicktime"})
    harness.complete(done, b"abc")
    assert list(storage.list_inputs(ORDER)) == [
        {"name": "a.mp4", "size": 3, "key": f"in/{ORDER}/a.mp4"}
    ]
    assert list(storage.list_inputs(OTHER)) == []


def test_many_files_listed_by_name(harness: StorageHarness) -> None:
    for name in ("c.jpg", "a.mp4", "b.mov"):
        target = harness.storage.create_upload_session(
            ORDER, {"name": name, "size": 1, "type": "video/mp4"}
        )
        harness.complete(target, b"x")
    assert [f["name"] for f in harness.storage.list_inputs(ORDER)] == ["a.mp4", "b.mov", "c.jpg"]


def test_upload_download_round_trip(harness: StorageHarness, tmp_path: Path) -> None:
    source = tmp_path / "text.mp4"
    source.write_bytes(b"reel")
    harness.storage.upload(source, f"out/{ORDER}/text.mp4", "video/mp4")
    copy = tmp_path / "copy.mp4"
    harness.storage.download(f"out/{ORDER}/text.mp4", copy)
    assert copy.read_bytes() == b"reel"
    assert harness.storage.signed_url(f"out/{ORDER}/text.mp4", "reel-text.mp4", 60)


def test_download_of_a_missing_key_fails(harness: StorageHarness, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        harness.storage.download(f"out/{ORDER}/none.mp4", tmp_path / "x")


def test_delete_order_removes_in_work_and_out_of_that_order_only(
    harness: StorageHarness, tmp_path: Path
) -> None:
    source = tmp_path / "f"
    source.write_bytes(b"1")
    for prefix in ("in", "work", "out"):
        harness.storage.upload(source, f"{prefix}/{ORDER}/f", "application/octet-stream")
    harness.storage.upload(source, f"in/{OTHER}/f", "application/octet-stream")
    harness.storage.delete_order(ORDER)
    harness.storage.delete_order(ORDER)  # twice is fine
    for prefix in ("in", "work", "out"):
        with pytest.raises(FileNotFoundError):
            harness.storage.download(f"{prefix}/{ORDER}/f", tmp_path / "x")
    assert [f["name"] for f in harness.storage.list_inputs(OTHER)] == ["f"]


@pytest.mark.parametrize("name", ["../escape.mp4", "a/b.mp4", "", ".hidden"])
def test_unsafe_file_names_are_refused(harness: StorageHarness, name: str) -> None:
    with pytest.raises(ValueError, match="file name"):
        harness.storage.create_upload_session(ORDER, {"name": name, "size": 1, "type": "video/mp4"})
