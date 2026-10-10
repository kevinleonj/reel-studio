"""Launcher port on the laptop: a dispatcher process that polls queued orders, takes a slot and
starts the editor; it also calls the sweep (docs/ARCHITECTURE.md §2, every 60 s locally).

`FakeEditor` (STEP-06 task 4) walks the real stage names with short sleeps and writes fixture
outputs, so the website can be driven end to end without spending anything on Claude. The real
editor's launcher arrives with the engine lane's worker command.
"""

import tempfile
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from reel_studio.core.errors import ErrorCode
from reel_studio.core.logging import get_logger
from reel_studio.core.ports import Clock, Launcher, OrderStore, Storage

log = get_logger(__name__)

# docs/EDITOR.md §1; `listening` only with "Keep the voice?" on, `revising` only when a gate fails.
STAGES = ("reading", "listening", "planning", "rendering", "checking", "saving")
FIXTURE_BYTES = b"fake editor output, not a video"


class FailureNotifier(Protocol):
    def order_failed(self, order_id: str, code: ErrorCode, stage: str) -> None: ...


class Dispatcher:
    def __init__(
        self,
        orders: OrderStore,
        launcher: Launcher,
        clock: Clock,
        *,
        sweep_every_s: int,
        notifier: FailureNotifier | None = None,
    ) -> None:
        self._orders = orders
        self._launcher = launcher
        self._clock = clock
        self._sweep_every = timedelta(seconds=sweep_every_s)
        self._last_sweep: datetime | None = None
        self._notifier = notifier

    def _failed(self, order_id: str, stage: str) -> None:
        if self._notifier is None:
            return
        try:
            self._notifier.order_failed(order_id, ErrorCode.JOB_KILLED, stage)
        except Exception:
            # Logged with its traceback; the other orders of this sweep still get their notices.
            log.exception(
                "failure notice not sent",
                extra={
                    "order_id": order_id,
                    "stage": "dispatcher",
                    "event": "notify",
                    "outcome": "error",
                },
            )

    def tick(self) -> None:
        """One pass: sweep when due, then start queued orders while slots are free."""
        now = self._clock.now()
        if self._last_sweep is None or now - self._last_sweep >= self._sweep_every:
            report = self._orders.sweep()
            self._last_sweep = now
            log.info(
                "sweep", extra={"event": "sweep", "stage": "dispatcher", "outcome": str(report)}
            )
            for failed in report["failed"]:
                self._failed(failed, "running")
        while (order_id := self._orders.next_queued()) is not None:
            if not self._orders.take_slot(order_id):
                return
            try:
                execution = self._launcher.launch(order_id)
            except Exception:
                # Any launch error: the order must fail and free its slot now, not hold it for
                # the 70-minute lease. Logged with its traceback.
                log.exception(
                    "launch failed",
                    extra={
                        "order_id": order_id,
                        "stage": "dispatcher",
                        "event": "launch",
                        "outcome": "error",
                    },
                )
                self._orders.fail(order_id, code=ErrorCode.JOB_KILLED)
                self._failed(order_id, "launch")
                continue
            log.info(
                "launched %s",
                execution,
                extra={
                    "order_id": order_id,
                    "stage": "dispatcher",
                    "event": "launch",
                    "outcome": "ok",
                },
            )

    def run_forever(self, poll_s: float, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                self.tick()
            except Exception:
                # One bad tick (the emulator not up yet, a timeout) must not end the dispatcher:
                # log it with its traceback and try again on the next tick.
                log.exception(
                    "dispatcher tick failed",
                    extra={"stage": "dispatcher", "event": "tick", "outcome": "error"},
                )
            stop.wait(poll_s)


class FakeEditor:
    """Stands in for reel-editor: same stage writes, same result shape, fixture files."""

    def __init__(
        self,
        orders: OrderStore,
        storage: Storage,
        *,
        stage_seconds: float,
        on_stage: Callable[[str], None] | None = None,
    ) -> None:
        self._orders = orders
        self._storage = storage
        self._stage_seconds = stage_seconds
        self._on_stage = on_stage

    def run(self, order_id: str) -> None:
        doc = self._orders.get(order_id)
        if doc is None or doc["status"] != "running":
            log.warning(
                "fake editor: order is not running",
                extra={"order_id": order_id, "stage": "editor", "outcome": "skipped"},
            )
            return
        settings = doc["settings"]
        keep_voice = isinstance(settings, dict) and bool(settings.get("keep_voice"))
        for stage in STAGES:
            if stage == "listening" and not keep_voice:
                continue
            self._orders.set_stage(order_id, name=stage)
            if self._on_stage is not None:
                self._on_stage(stage)
            time.sleep(self._stage_seconds)
        self._orders.finish(
            order_id, result=self._outputs(order_id, settings), cost={"usd_total": "0"}
        )

    def _outputs(self, order_id: str, settings: object) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as folder:
            fixture = Path(folder) / "fixture.mp4"
            fixture.write_bytes(FIXTURE_BYTES)
            for kind in ("text", "clean"):
                self._storage.upload(fixture, f"out/{order_id}/{kind}.mp4", "video/mp4")
        chips = settings.get("chips", []) if isinstance(settings, dict) else []
        return {
            "versions": [
                {"kind": "text", "key": f"out/{order_id}/text.mp4"},
                {"kind": "clean", "key": f"out/{order_id}/clean.mp4"},
            ],
            "duration_s": settings.get("length_s", 0) if isinstance(settings, dict) else 0,
            "caption": "Made by the fake editor: no Claude call, no real cut.",
            "text_lines": [{"at_s": 0, "text": "Fake editor"}],
            "music": {"mood": "calm", "tempo": "slow"},
            "left_out": [],
            "wishes": [
                {"wish": chip, "applied": False, "reason": "The fake editor does not edit."}
                for chip in chips
            ],
            "doubts": ["This Reel came from the fake editor."],
        }


class FakeEditorLauncher:
    """Launcher port: runs the fake editor on a thread; returns a made-up execution name."""

    def __init__(self, editor: FakeEditor, orders: OrderStore) -> None:
        self._editor = editor
        self._orders = orders

    def launch(self, order_id: str) -> str:
        thread = threading.Thread(
            target=self._run, args=(order_id,), name=f"fake-editor-{order_id}", daemon=True
        )
        thread.start()
        return thread.name

    def _run(self, order_id: str) -> None:
        try:
            self._editor.run(order_id)
        except Exception:
            # Broad on purpose: whatever kills the run thread must fail the order, not leave it
            # `running` until the lease expires. Logged with its traceback, never swallowed.
            log.exception(
                "fake editor crashed",
                extra={"order_id": order_id, "stage": "editor", "outcome": "error"},
            )
            self._orders.fail(order_id, code=ErrorCode.RENDER_ERROR)
