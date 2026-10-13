"""Start queued orders while running slots are free (docs/ARCHITECTURE.md §4, "One run per
order"). One rule for every caller: the laptop dispatcher, reel-api after Start, the sweep and
the editor job when it finishes (ARCHITECTURE §1, steps 8, 12 and 14).

A launch is never retried (the Launcher port is at most once). When it fails, the order fails at
once and frees its slot, instead of holding the slot for the 70-minute lease: an execution the
lost response may have started finds the order no longer running and exits before any work.
"""

from collections.abc import Callable

from reel_studio.core.errors import ErrorCode
from reel_studio.core.logging import get_logger
from reel_studio.core.ports import Launcher, OrderStore

log = get_logger(__name__)

OnLaunchFailed = Callable[[str], None]  # order id; tells Kevin and the customer


def launch_waiting(
    orders: OrderStore, launcher: Launcher, on_failed: OnLaunchFailed, *, stage: str
) -> None:
    """`stage` names the caller in the logs (dispatcher, start, sweep, editor)."""
    while (order_id := orders.next_queued()) is not None:
        if not orders.take_slot(order_id):
            return
        try:
            execution = launcher.launch(order_id)
        except Exception:
            # Any launch error: the order must fail and free its slot now. Logged with its
            # traceback, never swallowed.
            log.exception(
                "launch failed",
                extra={"order_id": order_id, "stage": stage, "event": "launch", "outcome": "error"},
            )
            orders.fail(order_id, code=ErrorCode.JOB_KILLED)
            on_failed(order_id)
            continue
        log.info(
            "launched %s",
            execution,
            extra={"order_id": order_id, "stage": stage, "event": "launch", "outcome": "ok"},
        )
