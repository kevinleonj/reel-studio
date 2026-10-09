"""In-memory Orders port: the same rules as Firestore (reel_studio/core/order_rules.py), one lock
standing in for transactions."""

import secrets
import threading
from collections.abc import Sequence
from copy import deepcopy

from reel_studio.core import order_rules as rules
from reel_studio.core.constants import RUN_TOKEN_BYTES
from reel_studio.core.errors import ErrorCode
from reel_studio.core.ports import Clock, NewOrder, QueueLimits, Record, SweepReport


class FakeOrders:
    def __init__(self, clock: Clock, limits: QueueLimits) -> None:
        self._clock = clock
        self._limits = limits
        self._lock = threading.Lock()
        self.orders: dict[str, rules.Doc] = {}
        self.weeks: dict[str, rules.Doc] = {}
        self.capacity: rules.Doc = rules.empty_capacity()

    # ------------------------------------------------------------ helpers

    def _write(self, changed: rules.Doc | None) -> None:
        if changed is not None:
            self.orders[changed["order_id"]] = changed

    def _give_place_back(self, before: rules.Doc | None, after: rules.Doc | None) -> None:
        if before is not None and after is not None and before["place_held"]:
            released = rules.release_place(self.weeks.get(before["week_id"]))
            if released is not None:
                self.weeks[before["week_id"]] = released

    def _free_slot(self, order_id: str) -> None:
        released = rules.release_slot(self.capacity, order_id)
        if released is not None:
            self.capacity = released

    # ------------------------------------------------------------ port

    def create_awaiting_payment(self, order: NewOrder) -> str:
        now = self._clock.now()
        with self._lock:
            week = rules.week_id(now)
            self.weeks[week] = rules.reserve_place(self.weeks.get(week), self._limits.weekly_cap)
            self.orders[order.order_id] = rules.new_order(order, now, self._limits.order_days)
        return order.order_id

    def mark_paid(self, order_id: str, stripe: Record) -> None:
        with self._lock:
            self._write(rules.mark_paid(self.orders.get(order_id), dict(stripe), self._clock.now()))

    def expire(self, order_id: str) -> None:
        with self._lock:
            before = self.orders.get(order_id)
            after = rules.expire(before)
            self._give_place_back(before, after)
            self._write(after)

    def set_manifest(self, order_id: str, *, files: Sequence[Record], bytes_declared: int) -> None:
        with self._lock:
            manifest = [dict(f) for f in files]
            self._write(rules.set_manifest(self.orders.get(order_id), manifest, bytes_declared))

    def queue(self, order_id: str) -> None:
        with self._lock:
            self._write(rules.queue(self.orders.get(order_id), self._clock.now()))

    def take_slot(self, order_id: str) -> bool:
        with self._lock:
            token = secrets.token_hex(RUN_TOKEN_BYTES)
            taken = rules.take_slot(
                self.orders.get(order_id), self.capacity, self._limits, self._clock.now(), token
            )
            if taken is None:
                return False
            self.orders[order_id], self.capacity = taken
            return True

    def release_slot(self, order_id: str) -> None:
        with self._lock:
            self._free_slot(order_id)

    def next_queued(self) -> str | None:
        with self._lock:
            waiting = [d for d in self.orders.values() if d["status"] == "queued"]
            waiting.sort(key=lambda d: d["queue"]["queued_at"])
            return waiting[0]["order_id"] if waiting else None

    def queue_position(self, order_id: str) -> int | None:
        with self._lock:
            mine = self.orders.get(order_id)
            if mine is None or mine["status"] != "queued":
                return None
            at = mine["queue"]["queued_at"]
            return sum(
                1
                for d in self.orders.values()
                if d["status"] == "queued" and d["queue"]["queued_at"] < at
            )

    def set_stage(self, order_id: str, *, name: str) -> None:
        with self._lock:
            self._write(rules.set_stage(self.orders.get(order_id), name, self._clock.now()))

    def finish(self, order_id: str, *, result: Record, cost: Record) -> None:
        with self._lock:
            now = self._clock.now()
            self._write(rules.finish(self.orders.get(order_id), dict(result), dict(cost), now))
            self._free_slot(order_id)

    def fail(self, order_id: str, *, code: ErrorCode) -> None:
        with self._lock:
            self._fail_locked(order_id, code)

    def _fail_locked(self, order_id: str, code: ErrorCode) -> None:
        before = self.orders.get(order_id)
        after = rules.fail(before, code, self._clock.now())
        self._give_place_back(before, after)
        self._write(after)
        self._free_slot(order_id)

    def pause(self, order_id: str, *, code: ErrorCode) -> None:
        with self._lock:
            self._write(rules.pause(self.orders.get(order_id), code))
            self._free_slot(order_id)
            self.capacity = {**self.capacity, "paused": True}

    def claim_email(self, order_id: str, kind: str) -> bool:
        with self._lock:
            changed = rules.claim_email(self.orders.get(order_id), kind, self._clock.now())
            self._write(changed)
            return changed is not None

    def get(self, order_id: str) -> Record | None:
        with self._lock:
            doc = self.orders.get(order_id)
            return deepcopy(doc) if doc is not None else None

    def mark_viewed(self, order_id: str) -> None:
        with self._lock:
            self._write(rules.mark_viewed(self.orders.get(order_id), self._clock.now()))

    def set_feedback(self, order_id: str, *, rating: int, comment: str) -> None:
        with self._lock:
            now = self._clock.now()
            self._write(rules.set_feedback(self.orders.get(order_id), rating, comment, now))

    def mark_deleted(self, order_id: str) -> None:
        with self._lock:
            self._write(rules.mark_deleted(self.orders.get(order_id)))

    def sweep(self) -> SweepReport:
        now = self._clock.now()
        report: SweepReport = {"failed": [], "expired": [], "abandoned": []}
        with self._lock:
            for order_id, doc in sorted(self.orders.items()):
                if rules.lease_expired(doc, now):
                    self._fail_locked(order_id, ErrorCode.JOB_KILLED)
                    report["failed"].append(order_id)
                elif rules.checkout_missed(doc, self._limits, now):
                    after = rules.expire(doc)
                    self._give_place_back(doc, after)
                    self._write(after)
                    report["expired"].append(order_id)
                else:
                    abandoned = rules.abandon(doc, self._limits, now)
                    if abandoned is not None:
                        self._write(abandoned)
                        report["abandoned"].append(order_id)
        return report
