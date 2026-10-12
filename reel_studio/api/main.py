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
from pathlib import Path
from typing import TextIO

from fastapi import FastAPI
from pydantic import ValidationError

from reel_studio.adapters.clock import SystemClock
from reel_studio.adapters.launcher_local import (
    Dispatcher,
    Editor,
    FakeEditor,
    FakeEditorLauncher,
    Sweep,
)
from reel_studio.adapters.launcher_real import MadeReel, MakeReel, RealEditor
from reel_studio.adapters.mailer_smtp import SmtpMailer
from reel_studio.adapters.payments_stripe import StripePayments, StripeSetup, build_client
from reel_studio.adapters.storage_local import LocalStorage
from reel_studio.api import payments
from reel_studio.api.app import create_app
from reel_studio.api.deps import ApiDeps
from reel_studio.api.notify import Notifier
from reel_studio.api.routes_local import DOWNLOAD_PATH, UPLOAD_PATH
from reel_studio.core import logging as reel_logging
from reel_studio.core.config import Config, load
from reel_studio.core.constants import SIGNING_KEY_BYTES, STRIPE_API_VERSION
from reel_studio.core.logging import get_logger
from reel_studio.core.order_rules import limits_from
from reel_studio.core.ports import Clock, OrderStore
from reel_studio.settings import WebSettings

# Named, not __name__: run with `python -m` this module is __main__, outside the `reel_studio`
# logger tree that configure() wires, and its lines would be dropped.
log = get_logger("reel_studio.api.main")
LIVE_KEY_PREFIXES = ("sk_live_", "rk_live_")  # Stripe's live-mode secret and restricted keys
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


def build_payments(settings: WebSettings, config: Config, clock: Clock) -> StripePayments | None:
    """Stripe in test mode (D58), or nothing with PAYMENTS=off. WebSettings has already
    refused PAYMENTS=stripe without its keys and ids."""
    if settings.payments == "off":
        return None
    key, secret = settings.stripe_secret_key, settings.stripe_webhook_secret
    price, coupon = settings.stripe_price_id, settings.stripe_coupon_id
    if key is None or secret is None or price is None or coupon is None:
        raise SystemExit("PAYMENTS=stripe needs its four STRIPE_ settings")  # unreachable
    if key.get_secret_value().startswith(LIVE_KEY_PREFIXES):
        raise SystemExit("the beta runs in Stripe test mode (D58): use a test-mode key")
    times = config.limits.stripe
    client = build_client(
        key.get_secret_value(),
        api_version=STRIPE_API_VERSION,
        timeout_s=times.timeout_s,
        max_network_retries=times.max_network_retries,
    )
    setup = StripeSetup(
        price_id=price,
        coupon_id=coupon,
        webhook_secret=secret.get_secret_value(),
        tolerance_s=times.webhook_tolerance_s,
    )
    return StripePayments(client, clock, setup)


def build_deps(
    settings: WebSettings, *, orders: OrderStore, clock: Clock, config: Config
) -> ApiDeps:
    storage = _storage(settings, clock)
    return ApiDeps(
        orders=orders,
        storage=storage,
        local_storage=storage,
        mailer=_mailer(settings, config),
        payments=build_payments(settings, config, clock),
        clock=clock,
        config=config,
        settings=settings,
        voice_available=settings.voice_available,
        web_dist=settings.web_dist,
    )


def build_dispatcher(
    settings: WebSettings,
    *,
    orders: OrderStore,
    clock: Clock,
    config: Config,
    make_reel: MakeReel | None = None,
) -> Dispatcher:
    """The fake editor (STEP-06 task 4), or the real one when `make_reel` is given (STEP-07
    task 9, `make dispatch-real`). The sweep is the API's own (payments.sweep), so with Stripe
    it asks Stripe about missed checkouts here too."""
    times = config.limits.dispatcher
    deps = build_deps(settings, orders=orders, clock=clock, config=config)
    notifier = Notifier(
        orders, deps.mailer, site_url=settings.site_url, kevin=settings.kevin_alert_email
    )
    editor: Editor = (
        FakeEditor(orders, deps.storage, stage_seconds=times.fake_stage_seconds)
        if make_reel is None
        else RealEditor(orders, deps.storage, make_reel, notifier=notifier)
    )
    return Dispatcher(
        orders,
        FakeEditorLauncher(editor, orders),
        clock,
        sweep=Sweep(lambda: payments.sweep(deps), every_s=times.sweep_seconds),
        notifier=notifier,
    )


def engine_make_reel(config: Config) -> MakeReel:
    """The engine's `make` (STEP-03) for one order: the same deps as `reel make`."""
    # Imported here: the api image has no editor extra; only the laptop's host dispatcher runs it.
    from reel_studio.cli.reel import real_deps  # noqa: PLC0415
    from reel_studio.editor import make, prompt  # noqa: PLC0415
    from reel_studio.editor.media import render  # noqa: PLC0415
    from reel_studio.settings import EditorSettings  # noqa: PLC0415

    try:
        editor_settings = EditorSettings()
    except ValidationError as error:
        raise SystemExit(settings_problem(error)) from None
    deps = real_deps()

    def make_reel(inputs: Path, out: Path, order: dict[str, object]) -> MadeReel:
        chips = order.get("chips")
        note = order.get("note")
        request = make.Request(
            folder=inputs,
            out=out,
            order=prompt.OrderSettings(
                style=str(order["style"]),
                length_s=int(str(order["length_s"])),
                text_lang=str(order["text_lang"]),
                voice=bool(order.get("keep_voice")),
                chips=tuple(str(c) for c in chips) if isinstance(chips, list) else (),
                note=str(note) if note else None,
            ),
        )
        made = make.make(
            request, deps.ports(editor_settings), deps.steps(inputs, editor_settings), config
        )
        final = made.final
        return MadeReel(
            text=out / render.TEXT,
            clean=out / render.CLEAN,
            cost_usd=made.cost,
            duration_s=final.render.timeline.duration,
            caption=made.edl.caption or "",
            doubts=[] if final.passed else [str(final.weakness)],
            music_hint=made.edl.music_hint,
        )

    return make_reel


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


def settings_problem(error: ValidationError) -> str:
    """Field names only: a pydantic message carries the input, which can be a key."""
    names = sorted({str(e["loc"][0]).upper() for e in error.errors() if e["loc"]})
    rule = [str(e["msg"]) for e in error.errors() if not e["loc"]]  # model-level, no input
    return " ".join(["settings missing or invalid (see .env.example):", *names, *rule])


def check(out: TextIO) -> int:
    """Validate the settings by the app's own rules, naming each bad field, never its value
    (a pydantic error message carries the input)."""
    try:
        WebSettings()
    except ValidationError as error:
        out.write(f"{settings_problem(error)}\n")
        return USAGE_ERROR
    out.write("settings ok\n")
    return 0


def create() -> FastAPI:
    """uvicorn's factory: settings are read (and validated) at startup, not at import."""
    reel_logging.configure()
    settings, config, clock = WebSettings(), load(), SystemClock()
    orders = firestore_orders(settings, config, clock)
    return create_app(build_deps(settings, orders=orders, clock=clock, config=config))


def dispatch(*, real: bool = False) -> None:
    reel_logging.configure()
    stop = threading.Event()

    def on_signal(_signum: int, _frame: object) -> None:
        stop.set()  # only this: logging from a signal handler can deadlock on the stream lock

    signal.signal(signal.SIGTERM, on_signal)  # `docker compose down` sends SIGTERM
    settings, config, clock = WebSettings(), load(), SystemClock()
    orders = firestore_orders(settings, config, clock)
    make_reel = engine_make_reel(config) if real else None
    dispatcher = build_dispatcher(
        settings, orders=orders, clock=clock, config=config, make_reel=make_reel
    )
    log.info("dispatcher started", extra={"stage": "dispatcher", "event": "start"})
    dispatcher.run_forever(config.limits.dispatcher.poll_seconds, stop)
    # An order the fake editor is running now stays `running` until its lease runs out and the
    # sweep fails it (70 min): the fake runs on a daemon thread and is not waited for.
    log.info("dispatcher stopped", extra={"stage": "dispatcher", "event": "stop"})


if __name__ == "__main__":
    if sys.argv[1:] == ["dispatch"]:
        dispatch()
    elif sys.argv[1:] == ["dispatch-real"]:
        dispatch(real=True)
    elif sys.argv[1:] == ["check"]:
        sys.exit(check(sys.stdout))
    else:
        raise SystemExit("usage: python -m reel_studio.api.main dispatch|dispatch-real|check")
