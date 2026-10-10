"""The laptop's chunk endpoint speaks Cloud Storage's resumable protocol (FACTS F307), so the web
app's upload code works unchanged against both. Same cases as tests/e2e/upload-*.spec.ts."""

from pathlib import Path

import pytest

from reel_studio.adapters.storage_local import ChunkAnswer, LocalStorage, SessionNotFound
from tests.contract.storage_adapters import NOW
from tests.fakes.clock import FrozenClock

ORDER = "a" * 32
SECRET = b"k" * 32


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(
        tmp_path / "data",
        upload_path="/api/local-upload",
        download_path="/api/local-files",
        signing_key=SECRET,
        clock=FrozenClock(NOW),
    )


def session_of(storage: LocalStorage, size: int, name: str = "a.mp4") -> str:
    target = storage.create_upload_session(ORDER, {"name": name, "size": size, "type": "video/mp4"})
    return str(target["upload_url"]).rsplit("/", 1)[1]


def test_status_query_on_a_new_session_has_no_range(storage: LocalStorage) -> None:
    session = session_of(storage, 10)
    assert storage.put_chunk(session, "bytes */10", b"") == ChunkAnswer(308, None)


def test_chunks_in_order_complete_the_file(storage: LocalStorage) -> None:
    session = session_of(storage, 10)
    assert storage.put_chunk(session, "bytes 0-3/10", b"0123") == ChunkAnswer(308, "bytes=0-3")
    assert storage.put_chunk(session, "bytes 4-9/10", b"456789") == ChunkAnswer(200, None)
    assert storage.put_chunk(session, "bytes */10", b"") == ChunkAnswer(200, None)
    assert list(storage.list_inputs(ORDER)) == [
        {"name": "a.mp4", "size": 10, "key": f"in/{ORDER}/a.mp4"}
    ]


def test_a_resent_chunk_is_ignored_where_already_persisted(
    storage: LocalStorage, tmp_path: Path
) -> None:
    session = session_of(storage, 6)
    storage.put_chunk(session, "bytes 0-3/6", b"0123")
    assert storage.put_chunk(session, "bytes 2-5/6", b"XX45") == ChunkAnswer(200, None)
    out = tmp_path / "out"
    storage.download(f"in/{ORDER}/a.mp4", out)
    assert out.read_bytes() == b"012345"


def test_a_chunk_past_the_offset_is_refused_with_the_real_offset(storage: LocalStorage) -> None:
    session = session_of(storage, 10)
    storage.put_chunk(session, "bytes 0-3/10", b"0123")
    assert storage.put_chunk(session, "bytes 6-9/10", b"6789") == ChunkAnswer(308, "bytes=0-3")


@pytest.mark.parametrize(
    ("header", "body"),
    [
        ("bytes 0-3/11", b"0123"),
        ("bytes 0-3/10", b"012"),
        ("nonsense", b""),
        ("bytes 0-12/10", b"x" * 13),
    ],
)
def test_malformed_chunks_are_refused(storage: LocalStorage, header: str, body: bytes) -> None:
    session = session_of(storage, 10)
    with pytest.raises(ValueError, match="Content-Range"):
        storage.put_chunk(session, header, body)


def read(storage: LocalStorage, tmp_path: Path, name: str = "a.mp4") -> bytes:
    out = tmp_path / "read-back"
    storage.download(f"in/{ORDER}/{name}", out)
    return out.read_bytes()


def test_a_file_chosen_again_after_a_reload_restarts_from_zero(
    storage: LocalStorage, tmp_path: Path
) -> None:
    old = session_of(storage, 10)
    storage.put_chunk(old, "bytes 0-3/10", b"0123")  # the page reloads here
    new = session_of(storage, 10)
    assert storage.put_chunk(new, "bytes 0-9/10", b"abcdefghij") == ChunkAnswer(200, None)
    assert read(storage, tmp_path) == b"abcdefghij"
    assert list(storage.list_inputs(ORDER)) == [
        {"name": "a.mp4", "size": 10, "key": f"in/{ORDER}/a.mp4"}
    ]


def test_two_sessions_for_one_name_never_interleave(storage: LocalStorage, tmp_path: Path) -> None:
    a, b = session_of(storage, 6), session_of(storage, 6)
    storage.put_chunk(a, "bytes 0-2/6", b"AAA")
    storage.put_chunk(b, "bytes 0-2/6", b"BBB")
    storage.put_chunk(a, "bytes 3-5/6", b"AAA")
    assert read(storage, tmp_path) == b"AAAAAA"
    storage.put_chunk(b, "bytes 3-5/6", b"BBB")
    assert read(storage, tmp_path) == b"BBBBBB"  # last completed wins, as in Cloud Storage


def test_bytes_written_before_a_lost_record_are_not_duplicated(
    storage: LocalStorage, tmp_path: Path
) -> None:
    session = session_of(storage, 8)
    storage.put_chunk(session, "bytes 0-3/8", b"0123")
    # Simulate a crash after appending but before the session record moved on: extra bytes on disk.
    partial = storage.partial_of(session)
    partial.write_bytes(partial.read_bytes() + b"4567")
    assert storage.put_chunk(session, "bytes 4-7/8", b"4567") == ChunkAnswer(200, None)
    assert read(storage, tmp_path) == b"01234567"


def test_deleting_the_order_removes_unfinished_bytes(storage: LocalStorage, tmp_path: Path) -> None:
    session = session_of(storage, 10)
    storage.put_chunk(session, "bytes 0-3/10", b"0123")
    storage.delete_order(ORDER)
    assert not storage.partial_of(session).exists()
    assert list((tmp_path / "data" / "sessions").iterdir()) == []


def test_a_broken_session_record_of_another_order_does_not_block_a_delete(
    storage: LocalStorage,
) -> None:
    storage.create_upload_session(ORDER, {"name": "y.mov", "size": 4, "type": "video/mp4"})
    (storage.partial_of("x").parent / "broken.json").write_text("")  # a write cut off mid-way
    storage.delete_order(ORDER)
    assert storage.list_inputs(ORDER) == []


def test_a_partial_shorter_than_its_record_is_resent_not_zero_filled(
    storage: LocalStorage, tmp_path: Path
) -> None:
    session = session_of(storage, 8)
    storage.put_chunk(session, "bytes 0-3/8", b"0123")
    storage.partial_of(session).write_bytes(b"01")  # the disk lost bytes the record counted
    assert storage.put_chunk(session, "bytes 4-7/8", b"4567") == ChunkAnswer(308, "bytes=0-1")
    storage.put_chunk(session, "bytes 2-7/8", b"234567")
    assert read(storage, tmp_path) == b"01234567"


def test_a_crash_after_the_file_moved_still_answers_complete(
    storage: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = session_of(storage, 4)
    real = Path.write_text

    def crash_on_complete(self: Path, data: str, *args: object, **kwargs: object) -> int:
        if self.name == f"{session}.tmp" and '"complete"' in data:  # records go via a temp file
            raise OSError("killed here")
        return real(self, data, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "write_text", crash_on_complete)
    with pytest.raises(OSError):
        storage.put_chunk(session, "bytes 0-3/4", b"0123")
    monkeypatch.undo()
    assert storage.put_chunk(session, "bytes */4", b"") == ChunkAnswer(200, None)


def test_two_orders_with_the_same_file_name_never_cross(
    storage: LocalStorage, tmp_path: Path
) -> None:
    other = "b" * 32
    a = session_of(storage, 4)
    b = str(
        storage.create_upload_session(other, {"name": "a.mp4", "size": 4, "type": "video/mp4"})[
            "upload_url"
        ]
    ).rsplit("/", 1)[1]
    storage.put_chunk(a, "bytes 0-3/4", b"AAAA")
    storage.put_chunk(b, "bytes 0-3/4", b"BBBB")
    storage.delete_order(ORDER)
    out = tmp_path / "other"
    storage.download(f"in/{other}/a.mp4", out)
    assert out.read_bytes() == b"BBBB"


def test_a_delete_that_cannot_remove_a_folder_raises(storage: LocalStorage, tmp_path: Path) -> None:
    session = session_of(storage, 1)
    storage.put_chunk(session, "bytes 0-0/1", b"x")
    inner = tmp_path / "data" / "objects" / "in" / ORDER
    inner.chmod(0o500)  # read and enter only: its files cannot be removed
    try:
        with pytest.raises(OSError):
            storage.delete_order(ORDER)
    finally:
        inner.chmod(0o700)
    assert [f["name"] for f in storage.list_inputs(ORDER)] == ["a.mp4"]


def test_unknown_session(storage: LocalStorage) -> None:
    with pytest.raises(SessionNotFound):
        storage.put_chunk("nope", "bytes */10", b"")


def test_signed_url_verifies_and_expires(storage: LocalStorage) -> None:
    url = storage.signed_url(f"out/{ORDER}/text.mp4", "reel-text.mp4", 60)
    path, query = url.split("?", 1)
    assert path.startswith("/api/local-files/")
    params = dict(part.split("=", 1) for part in query.split("&"))
    assert storage.verify_download(path.rsplit("/", 1)[1], params, now_s=int(params["exp"]) - 1)
    assert not storage.verify_download(path.rsplit("/", 1)[1], params, now_s=int(params["exp"]) + 1)
    assert not storage.verify_download(path.rsplit("/", 1)[1], {**params, "sig": "0" * 64}, now_s=0)
