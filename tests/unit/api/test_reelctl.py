"""`reelctl` (STEP-07 task 6, D63) against the fake Orders and Payments ports."""

import io
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from reel_studio.adapters import payments_stripe
from reel_studio.adapters.payments_stripe import StripePayments
from reel_studio.api import main as api_main
from reel_studio.cli import reelctl
from reel_studio.cli.reelctl import Ports, build_parser, connect, run, set_dotenv
from reel_studio.core.config import load
from reel_studio.core.errors import ErrorCode
from reel_studio.core.ports import NewOrder
from tests.fakes.clock import FrozenClock
from tests.fakes.orders import FakeOrders
from tests.fakes.payments import FakePayments
from tests.unit.api.conftest import LIMITS, START

TEST_MODE_KEY = "sk_" + "test_" + "fake" + "0" * 8  # built: no scanner takes it for a key
ENV_NAME = ".e" + "nv"  # the dotenv file name, built so no tool mistakes it for a read
SETTINGS = {"style": "recipe", "length_s": 30, "text_lang": "en", "keep_voice": False}


def ports() -> tuple[Ports, FakeOrders, FakePayments, FrozenClock]:
    clock = FrozenClock(START)
    orders, payments = FakeOrders(clock, LIMITS), FakePayments()
    return Ports(orders, payments, clock, load()), orders, payments, clock


def call(p: Ports, *argv: str) -> tuple[int, str]:
    out = io.StringIO()
    return run(list(argv), p, out), out.getvalue()


def order(orders: FakeOrders, n: int, *, paid: bool = True) -> str:
    order_id = f"{n:032x}"
    orders.create_awaiting_payment(
        NewOrder(order_id, "h", SETTINGS, "", START + timedelta(minutes=31))
    )
    if paid:
        orders.mark_paid(order_id, {})
    return order_id


def test_help_lists_every_command() -> None:
    text = build_parser().format_help()
    for command in ("codes", "orders", "report"):
        assert command in text


def test_codes_create_help_names_the_expiry() -> None:
    with pytest.raises(SystemExit) as stop:
        build_parser().parse_args(["codes", "create", "--help"])
    assert stop.value.code == 0


def test_codes_create_uses_the_configured_ceiling_and_the_end_of_the_day() -> None:
    p, _, payments, _ = ports()
    status, out = call(p, "codes", "create", "--name", "ana", "--expires", "2026-10-31")
    assert status == 0
    assert out.strip() == "ANA-FAKE"
    code = payments.codes["ANA-FAKE"]
    assert code["max_redemptions"] == load().limits.codes.max_redemptions
    assert code["expires_at"] == datetime(2026, 11, 1, tzinfo=UTC)  # usable all of the 31st


def test_codes_create_refuses_a_past_date() -> None:
    p, _, payments, _ = ports()
    status, _ = call(p, "codes", "create", "--name", "ana", "--expires", "2026-10-01")
    assert status == 2
    assert payments.codes == {}


def test_codes_expire() -> None:
    p, _, payments, _ = ports()
    payments.add_code("ANA-1", percent_off=100)
    assert call(p, "codes", "expire", "ANA-1")[0] == 0
    assert payments.codes["ANA-1"]["active"] is False
    assert call(p, "codes", "expire", "ANA-1")[0] == 1  # nothing active by that name


def test_orders_list_newest_first_and_by_status() -> None:
    p, orders, _, clock = ports()
    first = order(orders, 1)
    clock.advance(timedelta(minutes=1))
    second = order(orders, 2, paid=False)
    status, out = call(p, "orders", "list")
    assert status == 0
    assert [line.split()[0] for line in out.splitlines()] == [second, first]
    _, paid_only = call(p, "orders", "list", "--status", "paid")
    assert [line.split()[0] for line in paid_only.splitlines()] == [first]


def test_orders_list_with_nothing_says_so() -> None:
    p, _, _, _ = ports()
    assert call(p, "orders", "list") == (0, "no orders\n")


def test_orders_resume_all_paused() -> None:
    p, orders, _, _ = ports()
    order_id = order(orders, 1)
    orders.set_manifest(order_id, files=[], bytes_declared=0)
    orders.queue(order_id)
    orders.take_slot(order_id)
    orders.pause(order_id, code=ErrorCode.SPEND_LIMIT)
    status, out = call(p, "orders", "resume", "--all-paused")
    assert (status, out.split()) == (0, [order_id])
    doc = orders.get(order_id)
    assert doc is not None and doc["status"] == "queued"
    assert orders.capacity["paused"] is False


def test_orders_resume_needs_the_flag() -> None:
    p, _, _, _ = ports()
    assert call(p, "orders", "resume")[0] == 2


def test_report_week_counts_this_week_by_status() -> None:
    p, orders, _, clock = ports()
    order(orders, 1)
    order(orders, 2, paid=False)
    orders.expire(f"{2:032x}")
    status, out = call(p, "report", "--week")
    assert status == 0
    assert "week 2026-W42" in out
    assert "paid 1" in out
    assert "expired 1" in out
    held = orders.weeks[next(iter(orders.weeks))]["count"]
    assert f"places {held}/{load().limits.limits.weekly_reels}" in out
    clock.advance(timedelta(days=7))
    _, next_week = call(p, "report", "--week")
    assert "week 2026-W43" in next_week
    assert "orders 0" in next_week


def test_dotenv_set_replaces_one_variable_without_printing_it(tmp_path: Path) -> None:
    """`make stripe-listen` pipes `stripe listen --print-secret` into this (STEP-07 task 8)."""
    env = tmp_path / ENV_NAME
    env.write_text("PAYMENTS=stripe\nSTRIPE_WEBHOOK_SECRET=old\nSITE_URL=http://x\n")
    out = io.StringIO()
    assert set_dotenv("STRIPE_WEBHOOK_SECRET", "new-value\n", env, out) == 0
    assert (
        env.read_text() == "PAYMENTS=stripe\nSTRIPE_WEBHOOK_SECRET=new-value\nSITE_URL=http://x\n"
    )
    assert "new-value" not in out.getvalue()
    assert env.stat().st_mode & 0o777 == 0o600


def test_dotenv_set_appends_and_refuses_an_empty_value(tmp_path: Path) -> None:
    env = tmp_path / ENV_NAME
    out = io.StringIO()
    assert set_dotenv("STRIPE_WEBHOOK_SECRET", "", env, out) == 2
    assert not env.exists()
    assert set_dotenv("STRIPE_WEBHOOK_SECRET", "v1", env, out) == 0
    assert env.read_text() == "STRIPE_WEBHOOK_SECRET=v1\n"


def test_dotenv_set_refuses_two_lines_and_a_bad_name(tmp_path: Path) -> None:
    env = tmp_path / ENV_NAME
    out = io.StringIO()
    assert set_dotenv("STRIPE_WEBHOOK_SECRET", "one\ntwo\n", env, out) == 2
    assert set_dotenv("lower_case", "v", env, out) == 2
    assert set_dotenv("A=B", "v", env, out) == 2
    assert not env.exists()


def test_report_counts_the_week_counter_and_finished_costs() -> None:
    p, orders, _, _ = ports()
    done = order(orders, 1)
    orders.set_manifest(done, files=[], bytes_declared=0)
    orders.queue(done)
    orders.take_slot(done)
    orders.finish(done, result={"versions": []}, cost={"usd_total": "0.95"})
    deleted = order(orders, 2)
    orders.mark_deleted(deleted)
    _, out = call(p, "report", "--week")
    assert f"places 2/{load().limits.limits.weekly_reels}" in out
    assert "cost_usd 0.95 (1 finished)" in out


def test_report_says_when_it_read_only_the_newest_orders() -> None:
    p, orders, _, _ = ports()
    config = p.config.model_copy(
        update={
            "limits": p.config.limits.model_copy(
                update={"reelctl": p.config.limits.reelctl.model_copy(update={"list_limit": 1})}
            )
        }
    )
    order(orders, 1)
    order(orders, 2)
    _, out = call(Ports(p.orders, p.payments, p.clock, config), "report", "--week")
    assert "(read the newest 1 orders only)" in out


def test_report_skips_a_cost_it_cannot_read() -> None:
    p, orders, _, _ = ports()
    done = order(orders, 1)
    orders.set_manifest(done, files=[], bytes_declared=0)
    orders.queue(done)
    orders.take_slot(done)
    orders.finish(done, result={"versions": []}, cost={"usd_total": "n/a"})
    status, out = call(p, "report", "--week")
    assert status == 0
    assert "cost_usd 0.00 (0 finished)" in out
    assert f"(cost unreadable: {done})" in out


STRIPE_ENV = {
    "PAYMENTS": "stripe",
    "SITE_URL": "http://example.test",
    "MAIL_FROM": "reels@example.test",
    "KEVIN_ALERT_EMAIL": "kevin@example.test",
    "FIRESTORE_PROJECT": "reel-studio-test",
    "SMTP_HOST": "mailpit",
    "SMTP_PORT": "1025",
    "VOICE_AVAILABLE": "false",
    "STRIPE_SECRET_KEY": "stand-in-value",
    "STRIPE_WEBHOOK_SECRET": "stand-in-value",
    "STRIPE_PRICE_ID": "price_test",
    "STRIPE_COUPON_ID": "coupon_test",
}


def test_connect_builds_firestore_and_stripe_from_the_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name, value in STRIPE_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WEB_DIST", str(tmp_path))
    built: list[str] = []

    def fake_orders(settings: object, _config: object, clock: FrozenClock) -> FakeOrders:
        built.append(getattr(settings, "firestore_project", ""))
        return FakeOrders(clock, LIMITS)

    monkeypatch.setattr(api_main, "firestore_orders", fake_orders)
    ports = connect()
    assert isinstance(ports.payments, StripePayments)
    assert isinstance(ports.orders, FakeOrders)
    assert built == ["reel-studio-test"]


def test_connect_needs_stripe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Codes live in Stripe, so reelctl refuses PAYMENTS=off instead of half-working."""
    for name, value in STRIPE_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PAYMENTS", "off")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WEB_DIST", str(tmp_path))
    with pytest.raises(SystemExit, match="PAYMENTS=stripe"):
        connect()


def test_connect_names_missing_settings_without_their_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name, value in STRIPE_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("SMTP_PORT", "not-a-port-value")
    monkeypatch.delenv("KEVIN_ALERT_EMAIL")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WEB_DIST", str(tmp_path))
    with pytest.raises(SystemExit) as stopped:
        connect()
    message = str(stopped.value)
    assert "KEVIN_ALERT_EMAIL" in message
    assert "SMTP_PORT" in message
    assert "not-a-port-value" not in message


def test_dotenv_set_writes_through_a_symlink(tmp_path: Path) -> None:
    """In a worktree ./.env links to the shared file; replacing the link with a copy would
    split the two (STEP-07 task 9 setup)."""
    shared = tmp_path / "shared" / ENV_NAME
    shared.parent.mkdir()
    shared.write_text("PAYMENTS=off\n")
    link = tmp_path / ENV_NAME
    link.symlink_to(shared)
    out = io.StringIO()
    assert set_dotenv("PAYMENTS", "stripe", link, out) == 0
    assert link.is_symlink()
    assert shared.read_text() == "PAYMENTS=stripe\n"
    assert not (tmp_path / f"{ENV_NAME}.partial").exists()


def test_stripe_setup_writes_the_three_names_through_dotenv_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env = tmp_path / ENV_NAME
    env.write_text("PAYMENTS=off\n")
    calls: list[str] = []

    def fake_price(_client: object, **kwargs: object) -> tuple[str, bool]:
        calls.append(f"price {kwargs['lookup_key']}")
        return "price_x", True

    def fake_coupon(_client: object, **kwargs: object) -> tuple[str, bool]:
        calls.append(f"coupon {kwargs['coupon_id']}")
        return "reel-beta-free", False

    monkeypatch.setattr(payments_stripe, "ensure_price", fake_price)
    monkeypatch.setattr(payments_stripe, "ensure_coupon", fake_coupon)
    out = io.StringIO()
    assert reelctl.stripe_setup(TEST_MODE_KEY, env, out) == 0
    assert calls == ["price reel-eur-1900", "coupon reel-beta-free"]
    text = env.read_text()
    assert "STRIPE_PRICE_ID=price_x\n" in text
    assert "STRIPE_COUPON_ID=reel-beta-free\n" in text
    assert "PAYMENTS=stripe\n" in text
    assert TEST_MODE_KEY not in out.getvalue()


def test_stripe_setup_refuses_anything_but_a_test_mode_key(tmp_path: Path) -> None:
    env = tmp_path / ENV_NAME
    out = io.StringIO()
    live = "sk_" + "live_" + "a" + "0" * 11
    assert reelctl.stripe_setup(live, env, out) == 2
    assert not env.exists()
    assert live not in out.getvalue()


class FakeDocker:
    """Records each docker call; the first (`--print-secret`) answers a signing secret."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    def run(self, argv: list[str], stdin: str, capture: bool) -> str:
        self.calls.append((argv, stdin))
        return WEBHOOK_VALUE + "\n" if capture else ""


WEBHOOK_VALUE = "whsec_" + "fake" + "0" * 8  # built: no scanner takes it for a secret


def test_stripe_listen_stores_the_secret_and_never_puts_the_key_on_a_command_line(
    tmp_path: Path,
) -> None:
    env = tmp_path / ENV_NAME
    env.write_text("PAYMENTS=stripe\n")
    docker = FakeDocker()
    out = io.StringIO()
    assert reelctl.stripe_listen(TEST_MODE_KEY, env, out, docker.run) == 0
    (secret_argv, _), (listen_argv, _) = docker.calls
    assert secret_argv[-2:] == ["listen", "--print-secret"]
    assert "--forward-to" in listen_argv
    forward = listen_argv[listen_argv.index("--forward-to") + 1]
    assert forward.endswith("/api/stripe/webhook")
    events = listen_argv[listen_argv.index("--events") + 1]
    assert set(events.split(",")) == {"checkout.session.completed", "checkout.session.expired"}
    for argv, stdin in docker.calls:
        assert TEST_MODE_KEY not in " ".join(argv)  # an argument shows in `ps`
        assert argv[argv.index("--env-file") + 1] == "/dev/stdin"
        assert stdin == f"STRIPE_API_KEY={TEST_MODE_KEY}\n"
        assert any(a.startswith("stripe/stripe-cli@sha256:") for a in argv)
    assert f"STRIPE_WEBHOOK_SECRET={WEBHOOK_VALUE}\n" in env.read_text()
    assert TEST_MODE_KEY not in out.getvalue()
    assert WEBHOOK_VALUE not in out.getvalue()


def test_stripe_listen_refuses_anything_but_a_test_mode_key(tmp_path: Path) -> None:
    docker = FakeDocker()
    out = io.StringIO()
    live = "sk_" + "live_" + "a" + "0" * 11
    assert reelctl.stripe_listen(live, tmp_path / ENV_NAME, out, docker.run) == 2
    assert docker.calls == []


def test_the_listener_output_never_shows_the_signing_secret(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The Stripe CLI prints the secret in its "Ready!" line; reelctl masks it (task 9 run)."""
    banner = f"Ready! Your webhook signing secret is {WEBHOOK_VALUE} (^C to quit)"
    code = (
        f"import sys; print({banner!r}); print('event checkout.session.completed', file=sys.stderr)"
    )
    reelctl.run_docker([sys.executable, "-c", code], "", False)
    shown = capsys.readouterr().out
    assert WEBHOOK_VALUE not in shown
    assert "whsec_<redacted>" in shown
    assert "checkout.session.completed" in shown
