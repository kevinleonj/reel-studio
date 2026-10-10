"""Every OrderStore adapter the contract suite runs against."""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field

import pytest

from reel_studio.core.ports import OrderStore, QueueLimits
from tests.fakes.clock import FrozenClock
from tests.fakes.orders import FakeOrders


@dataclass(frozen=True)
class OrdersFactory:
    name: str
    build: Callable[[FrozenClock, QueueLimits], AbstractContextManager[OrderStore]]
    marks: tuple[pytest.MarkDecorator, ...] = field(default=())


@contextmanager
def _fake(clock: FrozenClock, limits: QueueLimits) -> Iterator[OrderStore]:
    yield FakeOrders(clock, limits)


@contextmanager
def _firestore(clock: FrozenClock, limits: QueueLimits) -> Iterator[OrderStore]:
    from tests.contract.firestore_emulator import emulator_orders  # noqa: PLC0415 (needs grpc)

    with emulator_orders(clock, limits) as adapter:
        yield adapter


ADAPTERS = (
    OrdersFactory("fake", _fake),
    OrdersFactory("firestore", _firestore, (pytest.mark.emulator,)),
)
