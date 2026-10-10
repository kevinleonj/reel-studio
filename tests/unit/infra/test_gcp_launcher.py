"""GcpLauncher: one Cloud Run job execution per order with ORDER_ID and RUN_TOKEN (F30).

The port is `launch(order_id)` (ARCHITECTURE.md §3); the run token comes from the order itself,
written by the `take_slot` transaction as `queue.run_token` (ARCHITECTURE.md §4).
"""

import json
import logging

import google.auth.exceptions
import pytest
from google.api_core import exceptions as google_exceptions
from google.cloud import run_v2

from reel_studio.adapters.gcp_launcher import GcpLauncher
from reel_studio.core import ports
from reel_studio.core.errors import CloudUnavailable
from tests.fakes.gcp import FakeJobsClient

JOB = "projects/test-project/locations/test-region/jobs/reel-editor"
TIMEOUT_S = 7.5


class FakeOrders:
    """The one read the launcher makes: the order document after take_slot."""

    def __init__(self, docs: dict[str, ports.Record]) -> None:
        self.docs = docs

    def get(self, order_id: str) -> ports.Record | None:
        return self.docs.get(order_id)


def running(token: str) -> ports.Record:
    return {"status": "running", "queue": {"run_token": token}}


def make(client: FakeJobsClient, docs: dict[str, ports.Record] | None = None) -> GcpLauncher:
    orders = FakeOrders(docs if docs is not None else {})
    return GcpLauncher(client, orders, job=JOB, timeout_s=TIMEOUT_S)


def env_of(call: dict[str, object]) -> dict[str, str]:
    request = call["request"]
    assert isinstance(request, run_v2.RunJobRequest)
    [override] = request.overrides.container_overrides
    return {env.name: env.value for env in override.env}


def test_satisfies_the_port() -> None:
    launcher: ports.Launcher = make(FakeJobsClient())
    assert launcher is not None


def test_one_launch_sends_the_order_and_its_run_token_without_retry() -> None:
    client = FakeJobsClient()
    order_id = "a" * 32

    name = make(client, {order_id: running("token-1")}).launch(order_id)

    assert name == client.operation_name
    [call] = client.calls
    request = call["request"]
    assert isinstance(request, run_v2.RunJobRequest)
    assert request.name == JOB
    assert env_of(call) == {"ORDER_ID": order_id, "RUN_TOKEN": "token-1"}
    # A retried start could launch twice and pay Claude twice; at most once (ports.Launcher).
    assert call["retry"] is None
    assert call["timeout"] == TIMEOUT_S


def test_many_launches_are_independent() -> None:
    client = FakeJobsClient()
    docs = {f"order-{i}": running(f"token-{i}") for i in range(3)}
    launcher = make(client, docs)

    for order_id in docs:
        launcher.launch(order_id)

    assert [env_of(c)["RUN_TOKEN"] for c in client.calls] == ["token-0", "token-1", "token-2"]


@pytest.mark.parametrize(
    "doc",
    [None, {"status": "running"}, {"status": "running", "queue": {}}, running("")],
    ids=["no-order", "no-queue", "no-token", "empty-token"],
)
def test_no_run_token_means_no_execution(doc: ports.Record | None) -> None:
    client = FakeJobsClient()
    docs = {} if doc is None else {"o1": doc}

    with pytest.raises(CloudUnavailable, match="run token"):
        make(client, docs).launch("o1")

    assert client.calls == []


@pytest.mark.parametrize(
    "error",
    [
        google_exceptions.PermissionDenied("actAs denied"),  # type: ignore[no-untyped-call]
        google.auth.exceptions.RefreshError("token expired"),  # type: ignore[no-untyped-call]
    ],
    ids=["api", "auth"],
)
def test_failure_becomes_cloud_unavailable_without_the_raw_text(
    error: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    client = FakeJobsClient(raises=error)

    with caplog.at_level(logging.INFO), pytest.raises(CloudUnavailable) as caught:
        make(client, {"order-1": running("token-1")}).launch("order-1")

    assert type(error).__name__ in str(caught.value)
    assert str(error.args[0]) not in str(caught.value)
    [record] = [r for r in caplog.records if r.name.endswith("gcp_launcher")]
    assert record.levelno == logging.ERROR
    assert record.__dict__["order_id"] == "order-1"
    assert record.__dict__["outcome"] == "error"
    assert "token-1" not in json.dumps(record.__dict__, default=str)


def test_success_is_logged_once_with_latency(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        make(FakeJobsClient(), {"order-1": running("token-1")}).launch("order-1")

    [record] = [r for r in caplog.records if r.name.endswith("gcp_launcher")]
    assert record.__dict__["event"] == "job_run"
    assert record.__dict__["outcome"] == "ok"
    assert isinstance(record.__dict__["latency_ms"], int)
    assert "token-1" not in record.getMessage()
