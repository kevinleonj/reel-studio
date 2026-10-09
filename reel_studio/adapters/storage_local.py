"""Storage port on the laptop's filesystem (Tier 1, `./data/`).

Uploads use the same resumable protocol as Cloud Storage (FACTS F307), answered by the API's
`PUT /api/local-upload/{session}`: so the browser code is identical in both tiers. Downloads are
API links signed with an HMAC key that lives only in this process (links die with a restart,
which is fine on a laptop).
"""

import hashlib
import hmac
import json
import re
import secrets
import shutil
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from urllib.parse import quote, unquote, urlencode

from reel_studio.core.constants import SECONDS_PER_MINUTE, UPLOAD_SESSION_BYTES
from reel_studio.core.ports import Clock, Record, UploadTarget

PREFIXES = ("in", "work", "out")
PARTIAL = ".part"
CHUNK = re.compile(r"^bytes (?P<start>\d+)-(?P<end>\d+)/(?P<total>\d+)$")
QUERY = re.compile(r"^bytes \*/(?P<total>\d+)$")
SAFE_NAME = re.compile(r"^[^/\\\x00]+$")


class SessionNotFound(LookupError):
    """No such upload session (unknown or deleted with its order)."""


@dataclass(frozen=True)
class ChunkAnswer:
    """What the chunk endpoint answers: 200 when the file is complete, else 308 with the
    persisted range (None when nothing is persisted yet)."""

    status: int  # an HTTPStatus value
    range: str | None


def check_file_name(name: str) -> str:
    if not SAFE_NAME.match(name) or name.startswith(".") or name in {"", "..", "."}:
        raise ValueError(f"unsafe file name: {name!r}")
    return name


class LocalStorage:
    def __init__(
        self,
        root: Path,
        *,
        upload_path: str,
        download_path: str,
        signing_key: bytes,
        clock: Clock,
    ) -> None:
        self._objects = root / "objects"
        self._sessions = root / "sessions"
        self._upload_path = upload_path
        self._download_path = download_path
        self._key = signing_key
        self._clock = clock
        self._objects.mkdir(parents=True, exist_ok=True)
        self._sessions.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ paths

    def _path(self, key: str) -> Path:
        path = (self._objects / key).resolve()
        if self._objects.resolve() not in path.parents:
            raise ValueError(f"key outside the store: {key!r}")
        return path

    def _session_file(self, session: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", session):
            raise SessionNotFound(session)
        return self._sessions / f"{session}.json"

    def _load(self, session: str) -> dict[str, object]:
        try:
            loaded: dict[str, object] = json.loads(self._session_file(session).read_text())
        except FileNotFoundError:
            raise SessionNotFound(session) from None
        return loaded

    # ------------------------------------------------------------ port

    def create_upload_session(self, order_id: str, file: Record) -> UploadTarget:
        name = check_file_name(str(file["name"]))
        size = int(str(file["size"]))
        session = secrets.token_urlsafe(UPLOAD_SESSION_BYTES)
        record = {"order_id": order_id, "key": f"in/{order_id}/{name}", "size": size, "received": 0}
        self._session_file(session).write_text(json.dumps(record))
        return {"name": name, "upload_url": f"{self._upload_path}/{session}"}

    def list_inputs(self, order_id: str) -> list[Record]:
        folder = self._path(f"in/{order_id}")
        if not folder.is_dir():
            return []
        files = sorted(p for p in folder.iterdir() if p.is_file())  # partials live with sessions
        return [
            {"name": p.name, "size": p.stat().st_size, "key": f"in/{order_id}/{p.name}"}
            for p in files
        ]

    def download(self, key: str, path: Path) -> None:
        source = self._path(key)
        if not source.is_file():
            raise FileNotFoundError(key)
        shutil.copyfile(source, path)

    def upload(self, path: Path, key: str, content_type: str) -> None:
        del content_type  # the filesystem keeps no metadata; the download route sets the type
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)

    def signed_url(self, key: str, filename: str, minutes: int) -> str:
        expires = int(self._clock.now().timestamp()) + minutes * SECONDS_PER_MINUTE
        quoted = quote(key, safe="")
        query = urlencode(
            {"exp": expires, "name": filename, "sig": self._sign(quoted, filename, expires)}
        )
        return f"{self._download_path}/{quoted}?{query}"

    def delete_order(self, order_id: str) -> None:
        """Removes in/, work/ and out/ of the order; any other failure propagates, so a caller
        never reports files as deleted that are still there."""
        for prefix in PREFIXES:
            folder = self._path(f"{prefix}/{order_id}")
            if folder.exists():
                shutil.rmtree(folder)
        for session in self._sessions.glob("*.json"):
            if json.loads(session.read_text()).get("order_id") == order_id:
                self.partial_of(session.stem).unlink(missing_ok=True)
                session.unlink(missing_ok=True)

    # ------------------------------------------------------------ laptop-only transport

    def _sign(self, quoted_key: str, filename: str, expires: int) -> str:
        message = f"{quoted_key}\n{filename}\n{expires}".encode()
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()

    def verify_download(self, quoted_key: str, params: dict[str, str], now_s: int) -> bool:
        try:
            expires = int(params["exp"])
            expected = self._sign(quoted_key, params["name"], expires)
            # Bytes, not str: compare_digest refuses non-ASCII strings with a TypeError.
            return (
                hmac.compare_digest(expected.encode(), params["sig"].encode()) and now_s <= expires
            )
        except (KeyError, ValueError):
            return False

    def open_download(self, quoted_key: str) -> Path:
        path = self._path(unquote(quoted_key))
        if not path.is_file():
            raise FileNotFoundError(quoted_key)
        return path

    def partial_of(self, session: str) -> Path:
        """The session's own bytes so far: never the final file, never shared by two sessions."""
        return self._sessions / f"{session}{PARTIAL}"

    def put_chunk(self, session: str, content_range: str, body: bytes) -> ChunkAnswer:
        record = self._load(session)
        size, received = int(str(record["size"])), int(str(record["received"]))
        partial = self.partial_of(session)
        query, chunk = QUERY.match(content_range), CHUNK.match(content_range)
        if query is not None:
            if int(query["total"]) != size:
                raise ValueError(
                    f"Content-Range total {query['total']} is not the session size {size}"
                )
        elif chunk is None:
            raise ValueError(f"malformed Content-Range: {content_range!r}")
        elif not record.get("complete"):
            start, end, total = int(chunk["start"]), int(chunk["end"]), int(chunk["total"])
            if total != size or end >= size or end < start or len(body) != end - start + 1:
                raise ValueError(
                    f"Content-Range {content_range!r} does not match the session or the body"
                )
            if start <= received <= end:
                # Bytes before `received` are already persisted and ignored, as Cloud Storage
                # does. The record is the truth: anything past it on disk (a write that crashed
                # before the record moved on) is cut off before appending.
                partial.touch()
                with partial.open("r+b") as handle:
                    handle.truncate(received)
                    handle.seek(received)
                    handle.write(body[received - start :])
                received = end + 1
                record = {**record, "received": received}
                self._session_file(session).write_text(json.dumps(record))
        if received == size and not record.get("complete"):
            self._finalise(partial, self._path(str(record["key"])), size)
            self._session_file(session).write_text(json.dumps({**record, "complete": True}))
        return self._answer(received, size)

    @staticmethod
    def _finalise(partial: Path, final: Path, size: int) -> None:
        """Move the finished bytes into place; a later finished upload of the same name replaces
        an earlier one (last wins, as in Cloud Storage)."""
        partial.touch()  # an empty file has no chunk to create it
        if partial.stat().st_size != size:
            raise ValueError(f"partial upload has {partial.stat().st_size} bytes, expected {size}")
        final.parent.mkdir(parents=True, exist_ok=True)
        partial.replace(final)

    @staticmethod
    def _answer(received: int, size: int) -> ChunkAnswer:
        if received == size:
            return ChunkAnswer(HTTPStatus.OK, None)
        persisted = f"bytes=0-{received - 1}" if received > 0 else None
        return ChunkAnswer(HTTPStatus.PERMANENT_REDIRECT, persisted)
