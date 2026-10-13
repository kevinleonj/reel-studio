"""`reel job`: one reel-editor execution on Cloud Run (MAIN-NEXT task 3; ARCHITECTURE §1 steps
9 to 13).

The launcher starts the job with ORDER_ID and RUN_TOKEN as overrides (gcp_launcher). The job
claims the run first (`claim_run`): when another execution already has it, or the order is no
longer running, it exits without touching anything. Then it downloads the files Start listed,
runs the engine, uploads both Reels, finishes the order, emails the result and starts the next
waiting order. Nothing is retried: Cloud Run runs the job with 0 retries (D52), because a second
run pays Claude twice.
"""

from dataclasses import dataclass

from pydantic import ValidationError

from reel_studio.adapters.clock import SystemClock
from reel_studio.adapters.launcher_real import MakeReel, RealEditor
from reel_studio.api.cloud import CloudAdapters, cloud_adapters, google_clients
from reel_studio.api.main import engine_make_reel, firestore_orders, settings_problem
from reel_studio.api.notify import Notifier
from reel_studio.core import logging as reel_logging
from reel_studio.core.config import Config, load, load_cloud
from reel_studio.core.dispatch import launch_waiting
from reel_studio.core.errors import ErrorCode
from reel_studio.core.logging import get_logger
from reel_studio.core.ports import Launcher, OrderStore, Storage
from reel_studio.settings import JobSettings, RuntimeSettings

log = get_logger(__name__)

OK, FAILED = 0, 1
STAGE = "job"


@dataclass(frozen=True)
class JobPorts:
    orders: OrderStore
    storage: Storage
    launcher: Launcher
    notifier: Notifier
    out_days: int  # how long the Reels stay, for the ready email

    @classmethod
    def of(
        cls, adapters: CloudAdapters, orders: OrderStore, runtime: RuntimeSettings, config: Config
    ) -> "JobPorts":
        notifier = Notifier(
            orders, adapters.mailer, site_url=runtime.site_url, kevin=runtime.kevin_alert_email
        )
        out_days = config.limits.retention.out_days
        return cls(orders, adapters.storage, adapters.launcher, notifier, out_days)


def _fields(order_id: str, event: str, outcome: str) -> dict[str, object]:
    return {"order_id": order_id, "stage": STAGE, "event": event, "outcome": outcome}


def _tell_failed(ports: JobPorts, order_id: str, code: ErrorCode, stage: str) -> None:
    try:
        ports.notifier.order_failed(order_id, code, stage)
    except Exception:
        # Logged with its traceback; the order's own state is already written.
        log.exception("failure notice not sent", extra=_fields(order_id, "notify", "error"))


def run_job(job: JobSettings, ports: JobPorts, make_reel: MakeReel) -> int:
    order_id = job.order_id
    if not ports.orders.claim_run(order_id, job.run_token.get_secret_value()):
        log.warning(
            "run not claimed: another execution has it, or the order is not running",
            extra=_fields(order_id, "claim", "skipped"),
        )
        return OK
    log.info("run claimed", extra=_fields(order_id, "claim", "ok"))
    outcome = OK
    try:
        # The engine's own refusals (ReelError) fail or pause the order inside RealEditor.
        RealEditor(ports.orders, ports.storage, make_reel, notifier=ports.notifier).run(order_id)
    except Exception:
        # Anything else that kills the run fails the order now, instead of holding its slot until
        # the lease runs out. Logged with its traceback, never swallowed.
        log.exception("editor crashed", extra=_fields(order_id, "run", "error"))
        ports.orders.fail(order_id, code=ErrorCode.RENDER_ERROR)
        _tell_failed(ports, order_id, ErrorCode.RENDER_ERROR, "rendering")
        outcome = FAILED
    else:
        ports.notifier.order_ready(order_id, out_days=ports.out_days)
    # This run's slot is free now (finish, fail or pause released it): start the oldest waiting
    # order (ARCHITECTURE §1 step 12).
    launch_waiting(
        ports.orders,
        ports.launcher,
        lambda waiting: _tell_failed(ports, waiting, ErrorCode.JOB_KILLED, "launch"),
        stage=STAGE,
    )
    return outcome


def main() -> int:
    """The Cloud Run job's command (`reel job`, infra/main/run.tf `args`)."""
    reel_logging.configure()
    errors = []
    for cls in (JobSettings, RuntimeSettings):
        try:
            cls()
        except ValidationError as error:
            errors.append(error)
    if errors:
        raise SystemExit(settings_problem(*errors))
    job, runtime = JobSettings(), RuntimeSettings()
    if runtime.tier != "cloud":
        raise SystemExit("reel job runs on Cloud Run only (TIER=cloud); use reel make on a laptop")
    config, cloud, clock = load(), load_cloud(), SystemClock()
    orders = firestore_orders(runtime, config, clock)
    clients = google_clients(runtime, cloud, resend_timeout_s=cloud.resend.timeout_s)
    adapters = cloud_adapters(runtime, cloud, clients, orders, mail_retries=cloud.resend.retries)
    make_reel = engine_make_reel(config)  # validates EditorSettings, names a missing key
    return run_job(job, JobPorts.of(adapters, orders, runtime, config), make_reel)
