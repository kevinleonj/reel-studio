"""The Firestore adapter wired to the local emulator, emptied before every test.

`FIRESTORE_EMULATOR_HOST` is set by tests/contract/run_emulator.py (`make test-emulator`); without
it the emulator cases skip with that hint instead of reaching any real project.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import pytest
from google.cloud import firestore

from reel_studio.adapters.orders_firestore import FirestoreOrders
from reel_studio.core.ports import QueueLimits
from tests.fakes.clock import FrozenClock

EMULATOR_ENV = "FIRESTORE_EMULATOR_HOST"
REQUIRE_ENV = "REEL_REQUIRE_EMULATOR"  # set by run_emulator.py
PROJECT = "reel-studio-test"
TIMEOUT_S = 10.0
MAX_ATTEMPTS = 5


@contextmanager
def emulator_orders(clock: FrozenClock, limits: QueueLimits) -> Iterator[FirestoreOrders]:
    host = os.environ.get(EMULATOR_ENV)
    if not host:
        if os.environ.get(REQUIRE_ENV) == "1":  # make test-emulator: a skip would be a failure
            pytest.fail(f"{EMULATOR_ENV} is not set but the emulators are required")
        pytest.skip(f"{EMULATOR_ENV} is not set: run `make test-emulator`")
    # The emulator's documented reset endpoint: delete every document of the project.
    reset = f"http://{host}/emulator/v1/projects/{PROJECT}/databases/(default)/documents"
    httpx.delete(reset, timeout=TIMEOUT_S).raise_for_status()
    client = firestore.Client(project=PROJECT)
    try:
        yield FirestoreOrders(client, clock, limits, timeout_s=TIMEOUT_S, max_attempts=MAX_ATTEMPTS)
    finally:
        client.close()  # type: ignore[no-untyped-call]  # google-cloud-firestore leaves it untyped
