"""The built site on the API's origin (docs/ARCHITECTURE.md §7, D71)."""

import pytest

from tests.unit.api.conftest import Api

NOINDEX = "noindex, nofollow"


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/", "landing"),
        ("/privacy", "privacy"),
        ("/robots.txt", "User-agent"),
        ("/sitemap-index.xml", "sitemapindex"),
    ],
)
def test_public_files_are_served_without_noindex(api: Api, path: str, body: str) -> None:
    response = api.client.get(path)
    assert response.status_code == 200
    assert body in response.text
    assert "X-Robots-Tag" not in response.headers


def test_html_is_never_cached(api: Api) -> None:
    assert api.client.get("/").headers["Cache-Control"] == "no-cache"


@pytest.mark.parametrize(
    ("path", "body"),
    [("/new", "new shell"), ("/o/" + "a" * 32, "order shell"), ("/o/anything", "order shell")],
)
def test_shells_carry_noindex_and_no_referrer(api: Api, path: str, body: str) -> None:
    response = api.client.get(path)
    assert response.status_code == 200
    assert body in response.text
    assert response.headers["X-Robots-Tag"] == NOINDEX
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_hashed_assets_are_immutable(api: Api) -> None:
    response = api.client.get("/_astro/app.abc123.js")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "public, max-age=31536000, immutable"


def test_api_answers_carry_noindex(api: Api) -> None:
    assert api.client.get("/api/config").headers["X-Robots-Tag"] == NOINDEX


@pytest.mark.parametrize("path", ["/nope", "/_astro/missing.js", "/../etc/passwd", "/o/a/b"])
def test_unknown_paths_get_the_built_404(api: Api, path: str) -> None:
    response = api.client.get(path)
    assert response.status_code == 404
    assert "not found" in response.text
