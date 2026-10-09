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
