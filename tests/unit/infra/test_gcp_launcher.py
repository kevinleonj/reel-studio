"""GcpLauncher: one Cloud Run job execution per order with ORDER_ID and RUN_TOKEN (F30)."""

import json
import logging

import pytest
from google.api_core import exceptions as google_exceptions
from google.cloud import run_v2

from reel_studio.adapters.gcp_launcher import GcpLauncher
from reel_studio.core import ports
from reel_studio.core.errors import CloudUnavailable
from tests.fakes.gcp import FakeJobsClient

JOB = "projects/test-project/locations/test-region/jobs/reel-editor"
TIMEOUT_S = 7.5


def make(client: FakeJobsClient) -> GcpLauncher:
    return GcpLauncher(client, job=JOB, timeout_s=TIMEOUT_S)


def env_of(call: dict[str, object]) -> dict[str, str]:
    request = call["request"]
    assert isinstance(request, run_v2.RunJobRequest)
    [override] = request.overrides.container_overrides
    return {env.name: env.value for env in override.env}


def test_satisfies_the_port() -> None:
    launcher: ports.Launcher = make(FakeJobsClient())
    assert launcher is not None


def test_one_launch_sends_the_overrides_without_retry() -> None:
    client = FakeJobsClient()

    name = make(client).launch("a" * 32, "token-1")

    assert name == client.operation_name
    [call] = client.calls
    request = call["request"]
    assert isinstance(request, run_v2.RunJobRequest)
    assert request.name == JOB
    assert env_of(call) == {"ORDER_ID": "a" * 32, "RUN_TOKEN": "token-1"}
    # A retried start could launch twice and pay Claude twice; the worker's token check is the
    # second line of defence, not a reason to retry here.
    assert call["retry"] is None
    assert call["timeout"] == TIMEOUT_S


def test_many_launches_are_independent() -> None:
    client = FakeJobsClient()
    launcher = make(client)

    for index in range(3):
        launcher.launch(f"order-{index}", f"token-{index}")

    assert [env_of(c)["RUN_TOKEN"] for c in client.calls] == ["token-0", "token-1", "token-2"]


def test_api_failure_becomes_cloud_unavailable_and_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    denied = google_exceptions.PermissionDenied("actAs denied")  # type: ignore[no-untyped-call]
    client = FakeJobsClient(raises=denied)

    with caplog.at_level(logging.INFO), pytest.raises(CloudUnavailable, match="PermissionDenied"):
        make(client).launch("order-1", "token-1")

    [record] = [r for r in caplog.records if r.name.endswith("gcp_launcher")]
    assert record.levelno == logging.ERROR
    assert record.__dict__["order_id"] == "order-1"
    assert record.__dict__["outcome"] == "error"
    assert "token-1" not in json.dumps(record.__dict__, default=str)


def test_success_is_logged_once_with_latency(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        make(FakeJobsClient()).launch("order-1", "token-1")

    [record] = [r for r in caplog.records if r.name.endswith("gcp_launcher")]
    assert record.__dict__["event"] == "job_run"
    assert record.__dict__["outcome"] == "ok"
    assert isinstance(record.__dict__["latency_ms"], int)
    assert "token-1" not in record.getMessage()
