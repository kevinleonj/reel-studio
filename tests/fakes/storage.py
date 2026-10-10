"""In-memory Storage port. `complete(target, data)` stands in for the browser's upload."""

from pathlib import Path

from reel_studio.adapters.storage_local import check_file_name
from reel_studio.core.ports import Record, UploadTarget

PREFIXES = ("in", "work", "out")


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.sessions: dict[str, str] = {}  # upload_url -> key
        self.signed: list[tuple[str, str, int]] = []

    def create_upload_session(self, order_id: str, file: Record) -> UploadTarget:
        name = check_file_name(str(file["name"]))
        url = f"fake://upload/{len(self.sessions)}"
        self.sessions[url] = f"in/{order_id}/{name}"
        return {"name": name, "upload_url": url}

    def complete(self, target: UploadTarget, data: bytes) -> None:
        self.objects[self.sessions[str(target["upload_url"])]] = data

    def list_inputs(self, order_id: str) -> list[Record]:
        prefix = f"in/{order_id}/"
        found = sorted(k for k in self.objects if k.startswith(prefix))
        return [
            {"name": k.removeprefix(prefix), "size": len(self.objects[k]), "key": k} for k in found
        ]

    def download(self, key: str, path: Path) -> None:
        if key not in self.objects:
            raise FileNotFoundError(key)
        path.write_bytes(self.objects[key])

    def upload(self, path: Path, key: str, content_type: str) -> None:
        del content_type
        self.objects[key] = path.read_bytes()

    def signed_url(self, key: str, filename: str, minutes: int) -> str:
        self.signed.append((key, filename, minutes))
        return f"fake://signed/{key}?name={filename}"

    def delete_order(self, order_id: str) -> None:
        for prefix in PREFIXES:
            for key in [k for k in self.objects if k.startswith(f"{prefix}/{order_id}/")]:
                del self.objects[key]
