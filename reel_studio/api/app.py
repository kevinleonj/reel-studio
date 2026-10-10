"""reel-api: the FastAPI app (docs/ARCHITECTURE.md §7). `create_app` takes every port ready-made,
so tests wire fakes and the composition root wires the real adapters."""

import time
from collections.abc import Awaitable, Callable
from http import HTTPStatus

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from reel_studio.api import routes_local, routes_orders, routes_public, static
from reel_studio.api.deps import ApiDeps, Limiters, deps_of
from reel_studio.api.errors import Refused, on_api_error, on_refused, on_validation
from reel_studio.api.ratelimit import SlidingWindow
from reel_studio.core.constants import MS_PER_S
from reel_studio.core.errors import ApiError
from reel_studio.core.logging import get_logger

__all__ = ["ApiDeps", "create_app"]

log = get_logger(__name__)
API_NOINDEX = {"X-Robots-Tag": "noindex, nofollow"}


def create_app(deps: ApiDeps) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.deps = deps
    quotas = deps.config.limits.limits
    app.state.limiters = Limiters(
        checkout=SlidingWindow(quotas.checkout_per_minute_per_address, deps.clock),
        order_calls=SlidingWindow(quotas.order_calls_per_minute_per_address, deps.clock),
    )
    app.add_exception_handler(ApiError, on_api_error)
    app.add_exception_handler(Refused, on_refused)
    app.add_exception_handler(RequestValidationError, on_validation)

    @app.middleware("http")
    async def log_and_tag(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.monotonic()
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers.update(API_NOINDEX)
            route = request.scope.get("route")
            # The route template, never the raw path or query string (no token, no signature).
            log.info(
                "%s %s %s",
                request.method,
                getattr(route, "path", "unmatched"),
                response.status_code,
                extra={
                    "order_id": request.path_params.get("order_id"),
                    "stage": "api",
                    "event": "request",
                    "latency_ms": round((time.monotonic() - started) * MS_PER_S),
                    "outcome": response.status_code,
                },
            )
        return response

    @app.post("/api/internal/sweep")
    def sweep(request: Request) -> JSONResponse:
        if not deps_of(request).sweep_auth(request):
            return JSONResponse({"error": "unauthorized"}, status_code=HTTPStatus.UNAUTHORIZED)
        return JSONResponse(dict(deps_of(request).orders.sweep()))

    app.include_router(routes_public.router)
    app.include_router(routes_orders.router)
    app.include_router(routes_local.router)
    app.include_router(static.router)  # last: it answers every GET nothing else claimed
    return app
