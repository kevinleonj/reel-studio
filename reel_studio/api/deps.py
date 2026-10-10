"""Everything the API needs, built once by the composition root and shared by the routes."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Request

from reel_studio.adapters.storage_local import LocalStorage
from reel_studio.api.ratelimit import SlidingWindow
from reel_studio.core.config import Config
from reel_studio.core.ports import Clock, Mailer, OrderStore, Storage
from reel_studio.settings import WebSettings


def refuse_all(_: Request) -> bool:
    """The laptop dispatcher sweeps in-process; the HTTP sweep is for Cloud Scheduler (STEP-08)."""
    return False


@dataclass(frozen=True)
class ApiDeps:
    orders: OrderStore
    storage: Storage
    local_storage: LocalStorage | None  # the laptop's chunk endpoint and signed downloads
    mailer: Mailer
    clock: Clock
    config: Config
    settings: WebSettings
    voice_available: bool  # D14: false when this server has no Gemini key
    web_dist: Path | None  # the Astro build; None serves no site (API only)
    sweep_auth: Callable[[Request], bool] = field(default=refuse_all)


@dataclass
class Limiters:
    checkout: SlidingWindow
    order_calls: SlidingWindow


def deps_of(request: Request) -> ApiDeps:
    deps: ApiDeps = request.app.state.deps
    return deps


def limiters_of(request: Request) -> Limiters:
    limiters: Limiters = request.app.state.limiters
    return limiters


def client_address(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"
