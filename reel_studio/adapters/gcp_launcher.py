"""Cloud adapter for the Launcher port: one Cloud Run job execution per order (F30, D52).

`jobs.run` with env overrides ORDER_ID and RUN_TOKEN (docs/ARCHITECTURE.md §4, "One run per
order"); the caller needs roles/run.jobsExecutorWithOverrides on the job. The call is never
retried here: a retry after a lost response could start a second execution and pay Claude twice.
The worker's run-token check stops a duplicate, and the sweep frees a slot that never started.
"""

import time
from typing import Protocol

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import run_v2

from reel_studio.core.errors import CloudUnavailable
from reel_studio.core.logging import get_logger, latency_ms

log = get_logger(__name__)

ORDER_ID_ENV = "ORDER_ID"  # read by the editor job's entry point (ARCHITECTURE.md §4)
RUN_TOKEN_ENV = "RUN_TOKEN"  # noqa: S105 - a variable name, not a secret (same source)


class Operation(Protocol):
    @property
    def operation(self) -> "OperationName": ...


class OperationName(Protocol):
    @property
    def name(self) -> str: ...


class JobsClient(Protocol):
    """The slice of google.cloud.run_v2.JobsClient this adapter uses."""

    def run_job(
        self, *, request: run_v2.RunJobRequest, retry: None, timeout: float
    ) -> Operation: ...


class GcpLauncher:
    def __init__(self, client: JobsClient, *, job: str, timeout_s: float) -> None:
        self._client = client
        self._job = job  # projects/{project}/locations/{region}/jobs/reel-editor
        self._timeout_s = timeout_s

    def launch(self, order_id: str, run_token: str) -> str:
        """Start one execution; returns the long-running operation's name."""
        override = run_v2.RunJobRequest.Overrides.ContainerOverride(
            env=[
                run_v2.EnvVar(name=ORDER_ID_ENV, value=order_id),
                run_v2.EnvVar(name=RUN_TOKEN_ENV, value=run_token),
            ]
        )
        request = run_v2.RunJobRequest(
            name=self._job,
            overrides=run_v2.RunJobRequest.Overrides(container_overrides=[override]),
        )
        started = time.monotonic()
        try:
            operation = self._client.run_job(request=request, retry=None, timeout=self._timeout_s)
        except GoogleAPICallError as exc:
            log.error(
                "job run failed error=%s",
                type(exc).__name__,
                extra=_fields(order_id, started, "error"),
            )
            raise CloudUnavailable(f"could not start the editor job: {exc}") from exc
        log.info("job run started", extra=_fields(order_id, started, "ok"))
        return operation.operation.name


def _fields(order_id: str, started: float, outcome: str) -> dict[str, object]:
    # The run token never reaches the log: it is the order's one-time start credential.
    return {
        "order_id": order_id,
        "stage": "launch",
        "event": "job_run",
        "latency_ms": latency_ms(started),
        "outcome": outcome,
    }
