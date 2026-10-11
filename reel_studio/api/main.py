"""The laptop composition root (STEP-06 task 6): reads WebSettings and config, builds the real
adapters, and hands them to the API and to the dispatcher. compose.yaml runs

    uvicorn --factory reel_studio.api.main:create        (the api service)
    python -m reel_studio.api.main dispatch              (the dispatcher service)
    python -m reel_studio.api.main check                 (make up, before anything starts)

Every outside service is reached only here; tests build the same objects with fakes through
`build_deps` and `build_dispatcher`.
"""

import secrets
import signal
import sys
import threading
from typing import TextIO

from fastapi import FastAPI
from pydantic import ValidationError

from reel_studio.adapters.clock import SystemClock
from reel_studio.adapters.launcher_local import Dispatcher, FakeEditor, FakeEditorLauncher
from reel_studio.adapters.mailer_smtp import SmtpMailer
from reel_studio.adapters.storage_local import LocalStorage
from reel_studio.api.app import create_app
from reel_studio.api.deps import ApiDeps
from reel_studio.api.notify import Notifier
from reel_studio.api.routes_local import DOWNLOAD_PATH, UPLOAD_PATH
from reel_studio.core import logging as reel_logging
from reel_studio.core.config import Config, load
from reel_studio.core.constants import SIGNING_KEY_BYTES
from reel_studio.core.logging import get_logger
from reel_studio.core.order_rules import limits_from
from reel_studio.core.ports import Clock, OrderStore
from reel_studio.settings import WebSettings

# Named, not __name__: run with `python -m` this module is __main__, outside the `reel_studio`
# logger tree that configure() wires, and its lines would be dropped.
log = get_logger("reel_studio.api.main")
USAGE_ERROR = 2


def _storage(settings: WebSettings, clock: Clock) -> LocalStorage:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    # A fresh key per process: links are re-signed on every status poll, so a restart only
    # invalidates links that were about to be replaced anyway. Nothing to store or leak.
    return LocalStorage(
        settings.data_dir,
        upload_path=UPLOAD_PATH,
        download_path=DOWNLOAD_PATH,
        signing_key=secrets.token_bytes(SIGNING_KEY_BYTES),
        clock=clock,
    )


def _mailer(settings: WebSettings, config: Config) -> SmtpMailer:
    return SmtpMailer(
        settings.smtp_host,
        settings.smtp_port,
        sender=settings.mail_from,
        timeout_s=config.limits.smtp.timeout_s,
    )


def _refuse_stripe(settings: WebSettings) -> None:
    if settings.payments != "off":
        raise SystemExit("PAYMENTS=stripe needs the Stripe adapter (STEP-07); use PAYMENTS=off")


def build_deps(
    settings: WebSettings, *, orders: OrderStore, clock: Clock, config: Config
) -> ApiDeps:
    _refuse_stripe(settings)
    storage = _storage(settings, clock)
    return ApiDeps(
        orders=orders,
        storage=storage,
        local_storage=storage,
        mailer=_mailer(settings, config),
        clock=clock,
        config=config,
        settings=settings,
        voice_available=settings.voice_available,
        web_dist=settings.web_dist,
    )


def build_dispatcher(
    settings: WebSettings, *, orders: OrderStore, clock: Clock, config: Config
) -> Dispatcher:
    """The fake editor until the engine lane's worker command exists (STEP-06 task 4)."""
    times = config.limits.dispatcher
    editor = FakeEditor(orders, _storage(settings, clock), stage_seconds=times.fake_stage_seconds)
    notifier = Notifier(
        orders,
        _mailer(settings, config),
        site_url=settings.site_url,
        kevin=settings.kevin_alert_email,
    )
    return Dispatcher(
        orders,
        FakeEditorLauncher(editor, orders),
        clock,
        sweep_every_s=times.sweep_seconds,
        notifier=notifier,
    )


def firestore_orders(settings: WebSettings, config: Config, clock: Clock) -> OrderStore:
    """The Firestore adapter; on the laptop the client finds the emulator through
    FIRESTORE_EMULATOR_HOST itself (F308)."""
    from google.cloud import firestore  # noqa: PLC0415 (api extra; unit tests never build it)

    from reel_studio.adapters.orders_firestore import FirestoreOrders  # noqa: PLC0415

    return FirestoreOrders(
        firestore.Client(project=settings.firestore_project),
        clock,
        limits_from(config),
        timeout_s=config.limits.firestore.timeout_s,
        max_attempts=config.limits.firestore.max_attempts,
    )


def check(out: TextIO) -> int:
    """Validate the settings by the app's own rules, naming each bad field, never its value
    (a pydantic error message carries the input)."""
    try:
        WebSettings()
    except ValidationError as error:
        names = sorted({str(e["loc"][0]).upper() for e in error.errors() if e["loc"]})
        out.write(f"settings missing or invalid (see .env.example): {' '.join(names)}\n")
        return USAGE_ERROR
    out.write("settings ok\n")
    return 0


def create() -> FastAPI:
    """uvicorn's factory: settings are read (and validated) at startup, not at import."""
    reel_logging.configure()
    settings, config, clock = WebSettings(), load(), SystemClock()
    _refuse_stripe(settings)
    orders = firestore_orders(settings, config, clock)
    return create_app(build_deps(settings, orders=orders, clock=clock, config=config))


def dispatch() -> None:
    reel_logging.configure()
    stop = threading.Event()

    def on_signal(_signum: int, _frame: object) -> None:
        stop.set()  # only this: logging from a signal handler can deadlock on the stream lock

    signal.signal(signal.SIGTERM, on_signal)  # `docker compose down` sends SIGTERM
    settings, config, clock = WebSettings(), load(), SystemClock()
    _refuse_stripe(settings)
    orders = firestore_orders(settings, config, clock)
    dispatcher = build_dispatcher(settings, orders=orders, clock=clock, config=config)
    log.info("dispatcher started", extra={"stage": "dispatcher", "event": "start"})
    dispatcher.run_forever(config.limits.dispatcher.poll_seconds, stop)
    # An order the fake editor is running now stays `running` until its lease runs out and the
    # sweep fails it (70 min): the fake runs on a daemon thread and is not waited for.
    log.info("dispatcher stopped", extra={"stage": "dispatcher", "event": "stop"})


if __name__ == "__main__":
    if sys.argv[1:] == ["dispatch"]:
        dispatch()
    elif sys.argv[1:] == ["check"]:
        sys.exit(check(sys.stdout))
    else:
        raise SystemExit("usage: python -m reel_studio.api.main dispatch|check")
