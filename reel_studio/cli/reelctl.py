"""`reelctl`: operator commands for the hosted beta (D63), run on Kevin's laptop with his own
Google Cloud login. Codes live in Stripe, orders in Firestore; both through their ports, so the
commands are tested against the fakes (`run`) and `main` only wires the real adapters."""

import argparse
import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TextIO

from reel_studio.core import order_rules as rules
from reel_studio.core.config import Config
from reel_studio.core.constants import (
    PRIVATE_FILE_MODE,
    STRIPE_API_VERSION,
    STRIPE_SECRET_TIMEOUT_S,
)
from reel_studio.core.ports import Clock, OrderStore, PaymentGateway, Record

USAGE_ERROR = 2  # argparse's own exit status for a bad command line
NOT_FOUND = 1
DOTENV_FILE = ".env"  # read by pydantic-settings (reel_studio/settings.py)
ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]*")


@dataclass(frozen=True)
class Ports:
    orders: OrderStore
    payments: PaymentGateway
    clock: Clock
    config: Config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reelctl", description="Operate the Reel Studio beta: codes, orders, pause."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    codes = commands.add_parser("codes", help="Stripe promotion codes for friends").add_subparsers(
        dest="action", required=True
    )
    create = codes.add_parser("create", help="a 100%%-off code for one friend")
    create.add_argument("--name", required=True, help="the friend's name, the start of the code")
    create.add_argument(
        "--expires",
        required=True,
        type=date.fromisoformat,
        help="last day the code works, YYYY-MM-DD (UTC)",
    )
    expire = codes.add_parser("expire", help="stop a code working now")
    expire.add_argument("code")

    orders = commands.add_parser("orders", help="orders in Firestore").add_subparsers(
        dest="action", required=True
    )
    listing = orders.add_parser("list", help="newest first")
    listing.add_argument("--status", help="only orders with this status, e.g. paused")
    resume = orders.add_parser("resume", help="reopen the service after a spend-limit pause")
    resume.add_argument(
        "--all-paused", action="store_true", help="put every paused order back in line (D26)"
    )

    report = commands.add_parser("report", help="weekly numbers")
    report.add_argument("--week", action="store_true", required=True, help="this ISO week")

    commands.add_parser(
        "stripe-listen",
        help="laptop, test mode: webhook secret into .env, then forward Stripe's events",
    )
    commands.add_parser(
        "stripe-setup",
        help="laptop, test mode: find or create the price and the beta coupon, write .env",
    )

    dotenv = commands.add_parser(
        "dotenv-set", help="store a value read from stdin in ./.env, never printing it"
    )
    dotenv.add_argument("name", help="e.g. STRIPE_WEBHOOK_SECRET (make stripe-listen)")
    return parser


def set_dotenv(name: str, raw: str, path: Path, out: TextIO) -> int:
    """Replace or append `name=value` in the dotenv file, written atomically with mode 600. The
    value comes from a pipe, so it is never on a command line or in the terminal."""
    value = raw.strip()
    if not ENV_NAME.fullmatch(name) or not value or "\n" in value:
        out.write(f"{name}: needs an upper-case name and one non-empty line on stdin\n")
        return USAGE_ERROR
    # A worktree's .env is a link to the shared file: write the file it points at, so the
    # rename below replaces that file and the link stays a link.
    path = path.resolve()
    lines = path.read_text().splitlines() if path.exists() else []
    entry = f"{name}={value}"
    kept = [entry if line.startswith(f"{name}=") else line for line in lines]
    if entry not in kept:
        kept.append(entry)
    partial = path.with_name(f"{path.name}.partial")
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PRIVATE_FILE_MODE)
    with os.fdopen(descriptor, "w") as handle:
        handle.write("".join(f"{line}\n" for line in kept))
    os.replace(partial, path)
    out.write(f"{name} set in {path.name}\n")
    return 0


TEST_KEY_PREFIXES = ("sk_test_", "rk_test_")  # Stripe's test-mode secret and restricted keys


def stripe_setup(api_key: str, env: Path, out: TextIO) -> int:
    """STEP-07 task 9 on the laptop: the price by its lookup key and the beta coupon, then
    STRIPE_PRICE_ID, STRIPE_COUPON_ID and PAYMENTS=stripe in the dotenv file. Test mode only;
    safe to run again. The key is never printed."""
    if not api_key.startswith(TEST_KEY_PREFIXES):
        out.write("STRIPE_SECRET_KEY is not a test-mode key; the laptop beta runs in test mode\n")
        return USAGE_ERROR
    # Imported here: `reelctl --help` works without the api extra (the Stripe SDK).
    from reel_studio.adapters.payments_stripe import (  # noqa: PLC0415
        build_client,
        ensure_coupon,
        ensure_price,
    )
    from reel_studio.core.config import load, load_cloud  # noqa: PLC0415

    cloud, times = load_cloud().stripe, load().limits.stripe
    client = build_client(
        api_key,
        api_version=STRIPE_API_VERSION,
        timeout_s=times.timeout_s,
        max_network_retries=times.max_network_retries,
    )
    lookup = f"reel-{cloud.currency}-{cloud.unit_amount_minor}"  # as scripts/cloud/stripe_setup.py
    price, made_price = ensure_price(
        client,
        lookup_key=lookup,
        unit_amount=cloud.unit_amount_minor,
        currency=cloud.currency,
        product_name=cloud.product_name,
    )
    coupon, made_coupon = ensure_coupon(client, coupon_id=times.coupon_id, name=times.coupon_name)
    out.write(f"price {lookup}: {'created' if made_price else 'found'}\n")
    out.write(f"coupon {coupon}: {'created' if made_coupon else 'found'}\n")
    for name, value in (
        ("STRIPE_PRICE_ID", price),
        ("STRIPE_COUPON_ID", coupon),
        ("PAYMENTS", "stripe"),
    ):
        if set_dotenv(name, value, env, out) != 0:
            return USAGE_ERROR
    return 0


# (argv, text for the child's stdin, capture stdout?) -> stdout; tests pass a fake.
Docker = Callable[[list[str], str, bool], str]
# Stripe webhook signing secrets; \S, not a narrower class, so a longer alphabet stays hidden.
SIGNING_SECRET = re.compile(r"whsec_\S+")


def run_docker(argv: list[str], stdin: str, capture: bool) -> str:
    """The key reaches the CLI through `--env-file /dev/stdin`: never an argument (it would show
    in `ps`) and never in this process's environment. The listener runs until Ctrl-C, so only
    the secret call has a timeout."""
    if capture:
        done = subprocess.run(  # noqa: S603 (a fixed docker argv built here)
            argv,
            input=stdin,
            capture_output=True,
            text=True,
            check=True,
            timeout=STRIPE_SECRET_TIMEOUT_S,
        )
        return done.stdout
    # The CLI prints the signing secret in its "Ready!" line: every line is masked on the way.
    with subprocess.Popen(  # noqa: S603 (a fixed docker argv built here)
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    ) as child:
        if child.stdin is None or child.stdout is None:
            raise RuntimeError("the listener's pipes did not open")
        child.stdin.write(stdin)
        child.stdin.close()
        for line in child.stdout:
            sys.stdout.write(SIGNING_SECRET.sub("whsec_<redacted>", line))
            sys.stdout.flush()
    if child.returncode != 0:
        raise subprocess.CalledProcessError(child.returncode, argv[:2])
    return ""


def stripe_listen(api_key: str, env: Path, out: TextIO, docker: Docker = run_docker) -> int:
    """STEP-07 task 8 without `stripe login`: the webhook signing secret into the dotenv file,
    then the Stripe CLI forwards the two checkout events to the laptop site (F313)."""
    if not api_key.startswith(TEST_KEY_PREFIXES):
        out.write("STRIPE_SECRET_KEY is not a test-mode key; the laptop beta runs in test mode\n")
        return USAGE_ERROR
    from reel_studio.adapters.payments_stripe import COMPLETED, EXPIRED  # noqa: PLC0415
    from reel_studio.core.config import load  # noqa: PLC0415

    events = (COMPLETED, EXPIRED)  # what the API handles
    times = load().limits.stripe
    base = ["docker", "run", "--rm", "-i", "--env-file", "/dev/stdin", times.cli_image]
    key_line = f"STRIPE_API_KEY={api_key}\n"  # the CLI reads STRIPE_API_KEY (F322)
    secret = docker([*base, "listen", "--print-secret"], key_line, True).strip()
    if set_dotenv("STRIPE_WEBHOOK_SECRET", secret, env, out) != 0:
        return USAGE_ERROR
    out.write(f"forwarding {', '.join(events)} to {times.listen_forward_to}\n")
    docker(
        [
            *base,
            "listen",
            "--events",
            ",".join(events),
            "--forward-to",
            times.listen_forward_to,
        ],
        key_line,
        False,
    )
    return 0


def _line(doc: Record) -> str:
    created = doc["created_at"]
    stamp = created.isoformat() if isinstance(created, datetime) else str(created)
    return f"{doc['order_id']} {doc['status']} {stamp} {doc.get('week_id', '')}"


def _codes(args: argparse.Namespace, ports: Ports, out: TextIO) -> int:
    if args.action == "expire":
        if not ports.payments.expire_code(args.code):
            out.write(f"no active code {args.code}\n")
            return NOT_FOUND
        out.write(f"expired {args.code}\n")
        return 0
    expires_at = datetime.combine(args.expires + timedelta(days=1), time(), tzinfo=UTC)
    if expires_at <= ports.clock.now():
        out.write(f"--expires {args.expires} is already over\n")
        return USAGE_ERROR
    created = ports.payments.create_code(
        name=args.name,
        expires_at=expires_at,
        max_redemptions=ports.config.limits.codes.max_redemptions,
    )
    out.write(f"{created['code']}\n")
    return 0


def _orders(args: argparse.Namespace, ports: Ports, out: TextIO) -> int:
    if args.action == "resume":
        if not args.all_paused:
            out.write("orders resume needs --all-paused\n")
            return USAGE_ERROR
        resumed = ports.orders.resume_paused()
        if not resumed:
            out.write("nothing was paused\n")
        for order_id in resumed:
            out.write(f"{order_id}\n")
        return 0
    found = ports.orders.list_orders(
        status=args.status, limit=ports.config.limits.reelctl.list_limit
    )
    if not found:
        out.write("no orders\n")
    for doc in found:
        out.write(f"{_line(doc)}\n")
    return 0


def _report(ports: Ports, out: TextIO) -> int:
    week = rules.week_id(ports.clock.now())
    limit = ports.config.limits.reelctl.list_limit
    newest = ports.orders.list_orders(status=None, limit=limit)
    this_week = [doc for doc in newest if doc.get("week_id") == week]
    statuses = Counter(str(doc["status"]) for doc in this_week)
    places = ports.orders.places_held(week)
    finished: list[Decimal] = []
    unreadable: list[str] = []
    for doc in this_week:
        try:
            usd = _usd(doc)
        except InvalidOperation:
            unreadable.append(str(doc["order_id"]))
            continue
        if usd is not None:
            finished.append(usd)
    out.write(f"week {week}\n")
    out.write(f"orders {len(this_week)}\n")
    out.write(f"places {places}/{ports.config.limits.limits.weekly_reels}\n")
    for status, count in sorted(statuses.items()):
        out.write(f"{status} {count}\n")
    out.write(f"cost_usd {sum(finished, Decimal()):.2f} ({len(finished)} finished)\n")
    for order_id in unreadable:
        out.write(f"(cost unreadable: {order_id})\n")
    if len(newest) == limit:
        out.write(f"(read the newest {limit} orders only)\n")
    return 0


def _usd(doc: Record) -> Decimal | None:
    """The editor's cost of a finished order (STEP-03 writes `usd_total` as a decimal string)."""
    cost = doc.get("cost")
    total = cost.get("usd_total") if isinstance(cost, dict) else None
    return Decimal(str(total)) if total is not None else None


def run(argv: Sequence[str], ports: Ports, out: TextIO) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "codes":
        return _codes(args, ports, out)
    if args.command == "orders":
        return _orders(args, ports, out)
    return _report(ports, out)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not args:  # bare `reelctl` shows the commands, as it did before STEP-07
        parser.print_help()
        return 0
    parsed = parser.parse_args(args)  # --help and usage errors need no connection
    if parsed.command == "stripe-setup":
        return stripe_setup(_test_key(), Path(DOTENV_FILE), sys.stdout)
    if parsed.command == "stripe-listen":
        return stripe_listen(_test_key(), Path(DOTENV_FILE), sys.stdout)
    if parsed.command == "dotenv-set":
        return set_dotenv(parsed.name, sys.stdin.read(), Path(DOTENV_FILE), sys.stdout)
    return run(args, connect(), sys.stdout)


def _test_key() -> str:
    from pydantic import ValidationError  # noqa: PLC0415

    from reel_studio.api.main import settings_problem  # noqa: PLC0415
    from reel_studio.settings import WebSettings  # noqa: PLC0415

    try:
        # payments="off": these commands create what PAYMENTS=stripe needs, so they read the key
        # before the price, the coupon and the webhook secret exist.
        settings = WebSettings(payments="off")
    except ValidationError as error:
        raise SystemExit(settings_problem(error)) from None
    if settings.stripe_secret_key is None:
        raise SystemExit("STRIPE_SECRET_KEY is not set in .env")
    return settings.stripe_secret_key.get_secret_value()


def connect() -> Ports:
    """The real adapters, from the same settings and composition root as the API (D63: run on
    Kevin's laptop with his own Google login). Codes live in Stripe, so PAYMENTS=stripe."""
    # Imported here: `reelctl --help` must work without the api extra's clients.
    from pydantic import ValidationError  # noqa: PLC0415

    from reel_studio.adapters.clock import SystemClock  # noqa: PLC0415
    from reel_studio.api.main import (  # noqa: PLC0415
        build_payments,
        firestore_orders,
        settings_problem,
    )
    from reel_studio.core.config import load  # noqa: PLC0415
    from reel_studio.settings import RuntimeSettings, WebSettings  # noqa: PLC0415

    try:
        settings, runtime = WebSettings(), RuntimeSettings()
    except ValidationError as error:
        raise SystemExit(settings_problem(error)) from None
    config, clock = load(), SystemClock()
    payments = build_payments(settings, config, clock)
    if payments is None:
        raise SystemExit("reelctl needs PAYMENTS=stripe and the Stripe settings in .env")
    return Ports(firestore_orders(runtime, config, clock), payments, clock, config)
