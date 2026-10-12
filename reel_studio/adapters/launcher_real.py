"""The real editor on the laptop (STEP-07 task 9): the dispatcher's launcher runs it on a thread,
as it runs the fake one. It downloads the order's uploads, asks the engine for the Reel, uploads
both versions and finishes the order with the engine's cost. The engine is injected (`make_reel`),
so this module never imports the editor; the composition root binds it (reel_studio.api.main).

The cloud runs the same steps as the reel-editor job (STEP-08); this is the laptop's stand-in.
"""

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from reel_studio.adapters.launcher_local import FailureNotifier
from reel_studio.core.errors import ReelError, SpendLimitReached
from reel_studio.core.logging import get_logger
from reel_studio.core.ports import OrderStore, Storage

log = get_logger(__name__)

VERSIONS = ("text", "clean")
VIDEO = "video/mp4"


@dataclass(frozen=True)
class MadeReel:
    text: Path
    clean: Path
    cost_usd: Decimal
    duration_s: float
    caption: str
    doubts: list[str]
    music_hint: str | None  # the engine's one line (EDITOR.md music_hint), or none


# (folder of the order's uploads, folder for the output, the order's settings) -> the Reel
MakeReel = Callable[[Path, Path, dict[str, object]], MadeReel]


class RealEditor:
    def __init__(
        self,
        orders: OrderStore,
        storage: Storage,
        make_reel: MakeReel,
        *,
        notifier: FailureNotifier,
    ) -> None:
        self._orders = orders
        self._storage = storage
        self._make_reel = make_reel
        self._notifier = notifier

    def run(self, order_id: str) -> None:
        doc = self._orders.get(order_id)
        if doc is None or doc["status"] != "running":
            log.warning(
                "real editor: order is not running",
                extra={"order_id": order_id, "stage": "editor", "outcome": "skipped"},
            )
            return
        settings = dict(doc["settings"]) if isinstance(doc["settings"], dict) else {}
        with tempfile.TemporaryDirectory(prefix="reel-order-") as folder:
            inputs, out = Path(folder) / "in", Path(folder) / "out"
            inputs.mkdir()
            self._orders.set_stage(order_id, name="reading")
            for item in self._storage.list_inputs(order_id):
                self._storage.download(str(item["key"]), inputs / str(item["name"]))
            self._orders.set_stage(order_id, name="planning")
            try:
                made = self._make_reel(inputs, out, settings)
            except ReelError as error:
                self._stopped(order_id, error)
                return
            self._orders.set_stage(order_id, name="saving")
            for kind, path in zip(VERSIONS, (made.text, made.clean), strict=True):
                self._storage.upload(path, f"out/{order_id}/{kind}.mp4", VIDEO)
        self._orders.finish(
            order_id,
            result={
                "versions": [{"kind": k, "key": f"out/{order_id}/{k}.mp4"} for k in VERSIONS],
                "duration_s": made.duration_s,
                "caption": made.caption,
                "text_lines": [],
                # The page's shape (web/src/lib/types.ts): the hint is the mood, no tempo apart.
                "music": {"mood": made.music_hint or "", "tempo": ""},
                "left_out": [],
                "wishes": [],
                "doubts": made.doubts,
            },
            cost={"usd_total": str(made.cost_usd)},
        )
        log.info(
            "real editor finished",
            extra={"order_id": order_id, "stage": "editor", "event": "finish", "outcome": "done"},
        )

    def _stopped(self, order_id: str, error: ReelError) -> None:
        """The engine's own refusal: the page shows its words (EDITOR.md §10). The monthly
        limit keeps the order and pauses the service (D26); everything else fails it and tells
        Kevin and the customer (the notifier writes only for failed orders)."""
        paused = isinstance(error, SpendLimitReached)
        log.warning(
            "real editor stopped: %s",
            error.code,
            extra={
                "order_id": order_id,
                "stage": "editor",
                "outcome": "paused" if paused else "failed",
            },
        )
        if paused:
            self._orders.pause(order_id, code=error.code)
            return
        self._orders.fail(order_id, code=error.code)
        try:
            self._notifier.order_failed(order_id, error.code, "planning")
        except Exception:
            # Logged with its traceback; the order's own state is already written.
            log.exception(
                "failure notice not sent",
                extra={
                    "order_id": order_id,
                    "stage": "editor",
                    "event": "notify",
                    "outcome": "error",
                },
            )
