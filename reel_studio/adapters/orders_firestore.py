"""Orders port on Firestore (Tier 1: the emulator; Tier 2: the (default) database, D53).

Every transition runs in one transaction that reads the documents, applies the pure rule from
reel_studio/core/order_rules.py and writes the result, so the fake and Firestore cannot drift.
Each call logs once with its latency (D74). Transactions retry up to `max_attempts` on
contention (the client's own bounded retry); reads carry an explicit timeout.
"""

import secrets
import time
from collections.abc import Callable, Sequence
from typing import Any

from google.cloud import firestore

from reel_studio.core import order_rules as rules
from reel_studio.core.constants import MS_PER_SECOND, RUN_TOKEN_BYTES
from reel_studio.core.errors import ErrorCode
from reel_studio.core.logging import get_logger
from reel_studio.core.ports import Clock, NewOrder, QueueLimits, Record, SweepReport

log = get_logger(__name__)

ORDERS = "orders"
LIMITS = "limits"


class FirestoreOrders:
    def __init__(
        self,
        client: firestore.Client,
        clock: Clock,
        limits: QueueLimits,
        *,
        timeout_s: float,
        max_attempts: int,
    ) -> None:
        self._db = client
        self._clock = clock
        self._limits = limits
        self._timeout_s = timeout_s
        self._max_attempts = max_attempts

    # ------------------------------------------------------------ plumbing

    def _order(self, order_id: str) -> firestore.DocumentReference:
        return self._db.collection(ORDERS).document(order_id)

    def _limit(self, doc_id: str) -> firestore.DocumentReference:
        return self._db.collection(LIMITS).document(doc_id)

    def _read(
        self, ref: firestore.DocumentReference, tx: firestore.Transaction
    ) -> rules.Doc | None:
        snapshot = ref.get(transaction=tx, timeout=self._timeout_s)
        return snapshot.to_dict() if snapshot.exists else None

    def _capacity(self, tx: firestore.Transaction) -> rules.Doc:
        found = self._read(self._limit(rules.CAPACITY_ID), tx)
        return found if found is not None else rules.empty_capacity()

    def _logged[T](self, event: str, order_id: str | None, call: Callable[[], T]) -> T:
        started = time.monotonic()
        extra: dict[str, Any] = {"order_id": order_id, "stage": "orders", "event": event}
        try:
            result = call()
        except Exception:
            extra.update(
                latency_ms=round((time.monotonic() - started) * MS_PER_SECOND), outcome="error"
            )
            log.exception("firestore %s failed", event, extra=extra)
            raise
        extra.update(latency_ms=round((time.monotonic() - started) * MS_PER_SECOND), outcome="ok")
        log.info("firestore %s", event, extra=extra)
        return result

    def _transaction[T](
        self, event: str, order_id: str | None, body: Callable[[firestore.Transaction], T]
    ) -> T:
        def run() -> T:
            tx = self._db.transaction(max_attempts=self._max_attempts)
            return firestore.transactional(body)(tx)  # type: ignore[no-any-return]

        return self._logged(event, order_id, run)

    def _give_place_back(
        self, tx: firestore.Transaction, week: rules.Doc | None, before: rules.Doc
    ) -> None:
        # Write only: the caller read `week` before any write in this transaction.
        released = rules.release_place(week) if before["place_held"] else None
        if released is not None:
            tx.set(self._limit(rules.week_doc_id(before["week_id"])), released)

    def _week_of(self, tx: firestore.Transaction, doc: rules.Doc | None) -> rules.Doc | None:
        if doc is None:
            return None
        return self._read(self._limit(rules.week_doc_id(doc["week_id"])), tx)

    # ------------------------------------------------------------ port

    def create_awaiting_payment(self, order: NewOrder) -> str:
        now = self._clock.now()
        week_ref = self._limit(rules.week_doc_id(rules.week_id(now)))

        def body(tx: firestore.Transaction) -> str:
            week = rules.reserve_place(self._read(week_ref, tx), self._limits.weekly_cap)
            tx.set(week_ref, week)
            tx.create(self._order(order.order_id), rules.new_order(order, now))
            return order.order_id

        return self._transaction("create_awaiting_payment", order.order_id, body)

    def _single(
        self, event: str, order_id: str, rule: Callable[[rules.Doc | None], rules.Doc | None]
    ) -> None:
        ref = self._order(order_id)

        def body(tx: firestore.Transaction) -> None:
            changed = rule(self._read(ref, tx))
            if changed is not None:
                tx.set(ref, changed)

        self._transaction(event, order_id, body)

    def mark_paid(self, order_id: str, stripe: Record) -> None:
        now = self._clock.now()
        self._single("mark_paid", order_id, lambda doc: rules.mark_paid(doc, dict(stripe), now))

    def expire(self, order_id: str) -> None:
        ref = self._order(order_id)

        def body(tx: firestore.Transaction) -> None:
            before = self._read(ref, tx)
            week = self._week_of(tx, before)
            after = rules.expire(before)
            if before is not None and after is not None:
                self._give_place_back(tx, week, before)
                tx.set(ref, after)

        self._transaction("expire", order_id, body)

    def set_manifest(self, order_id: str, *, files: Sequence[Record], bytes_declared: int) -> None:
        manifest = [dict(f) for f in files]
        self._single(
            "set_manifest", order_id, lambda doc: rules.set_manifest(doc, manifest, bytes_declared)
        )

    def queue(self, order_id: str) -> None:
        now = self._clock.now()
        self._single("queue", order_id, lambda doc: rules.queue(doc, now))

    def take_slot(self, order_id: str) -> bool:
        ref = self._order(order_id)
        capacity_ref = self._limit(rules.CAPACITY_ID)
        token = secrets.token_hex(RUN_TOKEN_BYTES)

        def body(tx: firestore.Transaction) -> bool:
            taken = rules.take_slot(
                self._read(ref, tx), self._capacity(tx), self._limits, self._clock.now(), token
            )
            if taken is None:
                return False
            tx.set(ref, taken[0])
            tx.set(capacity_ref, taken[1])
            return True

        return self._transaction("take_slot", order_id, body)

    def release_slot(self, order_id: str) -> None:
        capacity_ref = self._limit(rules.CAPACITY_ID)

        def body(tx: firestore.Transaction) -> None:
            released = rules.release_slot(self._capacity(tx), order_id)
            if released is not None:
                tx.set(capacity_ref, released)

        self._transaction("release_slot", order_id, body)

    def next_queued(self) -> str | None:
        def run() -> str | None:
            query = (
                self._db.collection(ORDERS)
                .where(filter=firestore.FieldFilter("status", "==", "queued"))
                .order_by("queue.queued_at")
                .limit(1)
            )
            for snapshot in query.stream(timeout=self._timeout_s):
                return str(snapshot.id)
            return None

        return self._logged("next_queued", None, run)

    def queue_position(self, order_id: str) -> int | None:
        def run() -> int | None:
            snapshot = self._order(order_id).get(timeout=self._timeout_s)
            mine = snapshot.to_dict() if snapshot.exists else None
            if mine is None or mine["status"] != "queued":
                return None
            ahead = (
                self._db.collection(ORDERS)
                .where(filter=firestore.FieldFilter("status", "==", "queued"))
                .where(
                    filter=firestore.FieldFilter("queue.queued_at", "<", mine["queue"]["queued_at"])
                )
            )
            # At most 50 a week (D55): counting ids is simpler to reason about than an aggregation.
            return sum(1 for _ in ahead.stream(timeout=self._timeout_s))

        return self._logged("queue_position", order_id, run)

    def set_stage(self, order_id: str, *, name: str) -> None:
        now = self._clock.now()
        self._single("set_stage", order_id, lambda doc: rules.set_stage(doc, name, now))

    def _end_run(
        self,
        event: str,
        order_id: str,
        rule: Callable[[rules.Doc | None], rules.Doc | None],
        *,
        pause: bool = False,
    ) -> None:
        """finish, fail and pause: change the order, free its slot, give the place back on fail."""
        ref = self._order(order_id)
        capacity_ref = self._limit(rules.CAPACITY_ID)

        def body(tx: firestore.Transaction) -> None:
            before = self._read(ref, tx)
            capacity = self._capacity(tx)
            week = self._week_of(tx, before)
            after = rule(before)
            if before is None or after is None:
                return
            tx.set(ref, after)
            if before["place_held"] and not after["place_held"]:
                self._give_place_back(tx, week, before)
            released = rules.release_slot(capacity, order_id) or capacity
            tx.set(capacity_ref, {**released, "paused": True} if pause else released)

        self._transaction(event, order_id, body)

    def finish(self, order_id: str, *, result: Record, cost: Record) -> None:
        now = self._clock.now()
        self._end_run(
            "finish", order_id, lambda doc: rules.finish(doc, dict(result), dict(cost), now)
        )

    def fail(self, order_id: str, *, code: ErrorCode) -> None:
        now = self._clock.now()
        self._end_run("fail", order_id, lambda doc: rules.fail(doc, code, now))

    def pause(self, order_id: str, *, code: ErrorCode) -> None:
        self._end_run("pause", order_id, lambda doc: rules.pause(doc, code), pause=True)

    def get(self, order_id: str) -> Record | None:
        def run() -> Record | None:
            snapshot = self._order(order_id).get(timeout=self._timeout_s)
            return snapshot.to_dict() if snapshot.exists else None

        return self._logged("get", order_id, run)

    def mark_viewed(self, order_id: str) -> None:
        now = self._clock.now()
        self._single("mark_viewed", order_id, lambda doc: rules.mark_viewed(doc, now))

    def set_feedback(self, order_id: str, *, rating: int, comment: str) -> None:
        now = self._clock.now()
        self._single(
            "set_feedback", order_id, lambda doc: rules.set_feedback(doc, rating, comment, now)
        )

    def mark_deleted(self, order_id: str) -> None:
        self._single("mark_deleted", order_id, rules.mark_deleted)

    def _ids(self, status: str) -> list[str]:
        query = self._db.collection(ORDERS).where(
            filter=firestore.FieldFilter("status", "==", status)
        )
        return sorted(str(s.id) for s in query.stream(timeout=self._timeout_s))

    def sweep(self) -> SweepReport:
        """Dead leases fail, missed checkouts expire, stale paid orders are abandoned. Each order
        is re-checked inside its own transaction, so a sweep racing a worker changes nothing."""
        now = self._clock.now()
        report: SweepReport = {"failed": [], "expired": [], "abandoned": []}
        for order_id in self._ids("running"):
            if self._changed(order_id, lambda doc: doc if rules.lease_expired(doc, now) else None):
                self.fail(order_id, code=ErrorCode.JOB_KILLED)
                report["failed"].append(order_id)
        for order_id in self._ids("awaiting_payment"):
            if self._changed(
                order_id, lambda doc: doc if rules.checkout_missed(doc, self._limits, now) else None
            ):
                self.expire(order_id)
                report["expired"].append(order_id)
        for order_id in self._ids("paid"):
            if self._changed(order_id, lambda doc: rules.abandon(doc, self._limits, now)):
                self._single("abandon", order_id, lambda doc: rules.abandon(doc, self._limits, now))
                report["abandoned"].append(order_id)
        return report

    def _changed(self, order_id: str, test: Callable[[rules.Doc], rules.Doc | None]) -> bool:
        doc = self.get(order_id)
        return doc is not None and test(dict(doc)) is not None
