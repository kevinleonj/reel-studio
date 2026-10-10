"""The Astro build on the API's own origin (D71, docs/ARCHITECTURE.md §7).

`/new` and every `/o/<id>` are static shells sent with `X-Robots-Tag: noindex, nofollow` and
`Referrer-Policy: no-referrer` (the token may still be in `?t=` on Stripe's return). Hashed
assets are immutable; HTML is never cached; anything else gets the built 404 page.
"""

from http import HTTPStatus
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response

from reel_studio.api.deps import deps_of
from reel_studio.core.constants import ASSET_MAX_AGE_S

router = APIRouter()

NOINDEX = {"X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer"}
NO_CACHE = {"Cache-Control": "no-cache"}
IMMUTABLE = {"Cache-Control": f"public, max-age={ASSET_MAX_AGE_S}, immutable"}
ASSETS = "_astro/"
PAGES = {"": "index.html", "privacy": "privacy/index.html"}
SHELLS = {"new": "new/index.html"}
ORDER_SHELL = "o/index.html"


def _inside(dist: Path, relative: str) -> Path | None:
    try:
        path = (dist / relative).resolve()
        found = dist.resolve() in path.parents and path.is_file()
    except (ValueError, OSError):  # a NUL byte, a name too long: not a file of the site
        return None
    return path if found else None


def _resolve(dist: Path, path: str) -> tuple[Path, dict[str, str]] | None:
    clean = path.strip("/")
    if clean in PAGES:
        found = _inside(dist, PAGES[clean])
        return (found, NO_CACHE) if found else None
    if clean in SHELLS:
        found = _inside(dist, SHELLS[clean])
        return (found, {**NO_CACHE, **NOINDEX}) if found else None
    parts = clean.split("/")
    if len(parts) == 2 and parts[0] == "o" and parts[1]:  # noqa: PLR2004 - "/o/<id>", one segment
        found = _inside(dist, ORDER_SHELL)
        return (found, {**NO_CACHE, **NOINDEX}) if found else None
    found = _inside(dist, clean)
    if found is None:
        return None
    if clean.startswith(ASSETS):
        return found, IMMUTABLE
    return found, NO_CACHE if found.suffix == ".html" else {}


@router.api_route(
    "/{path:path}", methods=["GET", "HEAD"], include_in_schema=False, response_model=None
)
def site(path: str, request: Request) -> Response:
    dist = deps_of(request).web_dist
    if dist is None:
        return PlainTextResponse("not found", status_code=HTTPStatus.NOT_FOUND)
    if path.startswith("api/"):  # an unknown API path answers like every other API refusal
        return JSONResponse({"error": "not_found"}, status_code=HTTPStatus.NOT_FOUND)
    resolved = _resolve(dist, path)
    if resolved is None:
        page = _inside(dist, "404.html")
        if page is None:
            return PlainTextResponse("not found", status_code=HTTPStatus.NOT_FOUND)
        return FileResponse(page, status_code=HTTPStatus.NOT_FOUND, headers=NO_CACHE)
    file, headers = resolved
    return FileResponse(file, headers=headers)
