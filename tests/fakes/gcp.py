"""Fakes for the Google Cloud clients the cloud adapters call (STEP-08 task 0).

Each fake records the calls it receives and answers like the real client, in shape only: field
names and return types follow docs/FACTS.md and the doc ledger (google-cloud-run 0.16.2,
google-cloud-storage 3.17.0). A fake raises the exception it is given to prove error paths.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from google.api_core.exceptions import NotFound

from reel_studio.adapters.storage_local import SessionNotFound


@dataclass
class FakeOperationProto:
    name: str


@dataclass
class FakeOperation:
    """google.api_core.operation.Operation: the long-running operation `run_job` returns."""

    operation: FakeOperationProto


@dataclass
class FakeJobsClient:
    """google.cloud.run_v2.JobsClient.run_job(request=..., retry=..., timeout=...)."""

    operation_name: str = "projects/p/locations/r/operations/op-1"
    raises: Exception | None = None
    calls: list[dict[str, object]] = field(default_factory=list)

    def run_job(self, *, request: object, retry: object, timeout: float) -> FakeOperation:
        self.calls.append({"request": request, "retry": retry, "timeout": timeout})
        if self.raises is not None:
            raise self.raises
        return FakeOperation(FakeOperationProto(self.operation_name))


@dataclass
class FakeBlob:
    """google.cloud.storage.Blob: the methods GcpStorage calls, recorded per call."""

    name: str
    bucket: "FakeBucket"
    size: int | None = None
    content_type: str | None = None

    def create_resumable_upload_session(
        self,
        *,
        content_type: str,
        size: int,
        origin: str,
        timeout: float,
        retry: object,
    ) -> str:
        self.bucket.record(
            "session", self.name, size=size, origin=origin, content_type=content_type
        )
        self.bucket.fail_if_asked()
        self.bucket.made += 1
        url = f"https://storage.test/upload/{self.name}?upload_id={self.bucket.made}"
        self.bucket.sessions[url] = (self.name, content_type)
        return url

    def generate_signed_url(self, **options: object) -> str:
        """Keyword options as the adapter passes them; tests assert the exact set."""
        self.bucket.record("sign", self.name, **options)
        self.bucket.fail_if_asked()
        return f"https://storage.test/{self.name}?X-Goog-Signature=abc"

    def download_to_filename(self, filename: str, *, timeout: float, retry: object) -> None:
        self.bucket.record("download", self.name, filename=filename)
        self.bucket.fail_if_asked()
        Path(filename).write_bytes(self.bucket.stored(self.name))

    def download_as_text(self, *, timeout: float, retry: object) -> str:
        self.bucket.record("read", self.name)
        self.bucket.fail_if_asked()
        return self.bucket.stored(self.name).decode()

    def upload_from_string(
        self, data: str, *, content_type: str, timeout: float, retry: object
    ) -> None:
        self.bucket.record("write", self.name, content_type=content_type)
        self.bucket.fail_if_asked()
        self.bucket.contents[self.name] = data.encode()

    def upload_from_filename(
        self, filename: str, *, content_type: str, timeout: float, retry: object
    ) -> None:
        self.bucket.record("upload", self.name, content_type=content_type)
        self.bucket.fail_if_asked()
        self.bucket.contents[self.name] = Path(filename).read_bytes()

    def delete(self, *, timeout: float, retry: object) -> None:
        self.bucket.record("delete", self.name)
        self.bucket.fail_if_asked()
        if self.name not in self.bucket.contents:  # the real client answers 404 here too
            raise NotFound(f"No such object: {self.bucket.name}/{self.name}")  # type: ignore[no-untyped-call]
        del self.bucket.contents[self.name]


@dataclass
class FakeBucket:
    name: str = "test-media"
    contents: dict[str, bytes] = field(default_factory=dict)
    types: dict[str, str] = field(default_factory=dict)
    raises: Exception | None = None
    # Listed but already deleted: the race between list and delete.
    stale: set[str] = field(default_factory=set)
    calls: list[tuple[str, str, dict[str, object]]] = field(default_factory=list)
    # Open resumable sessions: session URL -> (object name, content type).
    sessions: dict[str, tuple[str, str]] = field(default_factory=dict)
    made: int = 0

    def stored(self, name: str) -> bytes:
        if name not in self.contents:  # the real client raises NotFound for a missing object
            raise NotFound(f"No such object: {self.name}/{name}")  # type: ignore[no-untyped-call]
        return self.contents[name]

    def complete(self, url: str, data: bytes) -> None:
        """The browser's PUT of the whole file to a session; a cancelled one answers 4xx."""
        if url not in self.sessions:
            raise SessionNotFound(url)
        name, content_type = self.sessions.pop(url)
        self.contents[name] = data
        self.types[name] = content_type

    def cancel(self, url: str) -> None:
        """DELETE on the session URL (Cloud Storage answers 499, F89)."""
        self.record("cancel", url)
        self.sessions.pop(url, None)

    def record(self, action: str, key: str, **details: object) -> None:
        self.calls.append((action, key, details))

    def fail_if_asked(self) -> None:
        if self.raises is not None:
            raise self.raises

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(name, self)

    def list_blobs(self, *, prefix: str, timeout: float, retry: object) -> Iterator[FakeBlob]:
        self.record("list", prefix)
        self.fail_if_asked()
        for key in sorted(set(self.contents) | self.stale):
            if key.startswith(prefix):
                size = len(self.contents[key]) if key in self.contents else None
                yield FakeBlob(key, self, size, self.types.get(key))
