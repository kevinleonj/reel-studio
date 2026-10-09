"""Laptop-only transport for the filesystem Storage adapter: the chunked upload endpoint that
speaks Cloud Storage's resumable protocol (F307), and HMAC-signed downloads."""

from http import HTTPStatus
from urllib.parse import quote

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse

from reel_studio.adapters.storage_local import SessionNotFound
from reel_studio.api.deps import deps_of
from reel_studio.api.errors import Refused, not_found
from reel_studio.core.constants import BYTES_PER_MIB
from reel_studio.core.logging import get_logger

log = get_logger(__name__)
router = APIRouter()


@router.put("/api/local-upload/{session}")
async def put_chunk(session: str, request: Request) -> Response:
    deps = deps_of(request)
    if deps.local_storage is None:
        raise not_found()
    max_body = deps.config.limits.upload.chunk_mib * BYTES_PER_MIB
    declared = request.headers.get("Content-Length")
    if declared is not None and declared.isdigit() and int(declared) > max_body:
        raise Refused("chunk_too_large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
    body = await request.body()
    try:
        answer = deps.local_storage.put_chunk(
            session, request.headers.get("Content-Range", ""), body
        )
    except SessionNotFound:
        raise not_found() from None
    except ValueError as error:
        # A malformed or inconsistent Content-Range is a protocol error, as Cloud Storage answers.
        log.info(
            "chunk refused: %s",
            error,
            extra={"stage": "upload", "event": "chunk", "outcome": "refused"},
        )
        raise Refused("bad_content_range", HTTPStatus.BAD_REQUEST) from error
    headers = {"Range": answer.range} if answer.range is not None else {}
    return Response(status_code=answer.status, headers=headers)


@router.get("/api/local-files/{key:path}")
def download(key: str, request: Request) -> FileResponse:
    deps = deps_of(request)
    storage = deps.local_storage
    # The router hands over the decoded key; the signature covers its quoted form.
    quoted_key = quote(key, safe="")
    params = dict(request.query_params)
    now_s = int(deps.clock.now().timestamp())
    if storage is None or not storage.verify_download(quoted_key, params, now_s):
        raise not_found()
    try:
        path = storage.open_download(quoted_key)
    except (FileNotFoundError, ValueError):
        raise not_found() from None
    return FileResponse(path, filename=params["name"], content_disposition_type="attachment")
