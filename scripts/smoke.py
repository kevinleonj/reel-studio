#!/usr/bin/env python3
"""`make smoke URL=<service url>`: outside-in checks of the live beta (docs/INFRA.md §4).

    uv run python scripts/smoke.py --url https://reel-api-<number>.<region>.run.app

The URL alone is enough: its F61 shape names the service, the project number and the region.
Checks: GET /health is 200; GET / serves the built site; GET /api/config is a JSON object; the
live service has max instances 2 and cpu_idle; the job has a 3600 s timeout and 0 retries; the
orders TTL policy is ACTIVE, or CREATING right after a first deploy (Terraform does not
wait for it, infra/main/firestore.tf). Reads use
Application Default Credentials (the deploy job's Workload Identity, or `gcloud auth
application-default login` on the laptop). Exit 0 when every check passes, 1 otherwise, 2 for
an unusable URL.
"""

import argparse
import functools
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

import httpx
from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import GoogleAuthError
from google.cloud import firestore_admin_v1, run_v2

from reel_studio.core.config import Smoke, load_cloud
from scripts.cloud._shell import SERVICE_URL as SERVICE_URL_TEMPLATE

EXIT_CLEAN, EXIT_FOUND, EXIT_ERROR = 0, 1, 2
# F61: https://SERVICE-PROJECT_NUMBER.REGION.run.app
SERVICE_URL = re.compile(
    r"^https://(?P<service>[a-z][a-z0-9-]*?)-(?P<number>\d+)\.(?P<region>[a-z0-9-]+)\.run\.app/?$"
)
JOB_NAME = "reel-editor"  # infra/main/locals.tf editor_name
TTL_FIELD = "databases/(default)/collectionGroups/orders/fields/expires_at"  # infra firestore.tf
TtlState = firestore_admin_v1.Field.TtlConfig.State


class Services(Protocol):
    def get_service(self, *, name: str, timeout: float) -> run_v2.Service: ...


class Jobs(Protocol):
    def get_job(self, *, name: str, timeout: float) -> run_v2.Job: ...


class Admin(Protocol):
    def get_field(self, *, name: str, timeout: float) -> firestore_admin_v1.Field: ...


@dataclass(frozen=True)
class Target:
    service: str
    number: str
    region: str

    @property
    def base_url(self) -> str:
        return SERVICE_URL_TEMPLATE.format(
            service=self.service, number=self.number, region=self.region
        )

    def resource(self, kind: str, name: str) -> str:
        return f"projects/{self.number}/locations/{self.region}/{kind}/{name}"


@dataclass(frozen=True)
class Clients:
    http: httpx.Client
    services: Services
    jobs: Jobs
    admin: Admin


@dataclass(frozen=True)
class Result:
    name: str
    ok: bool
    detail: str


def parse(url: str) -> Target:
    match = SERVICE_URL.fullmatch(url.strip())
    if match is None:
        raise ValueError(f"{url!r} is not a https://<service>-<number>.<region>.run.app URL (F61)")
    return Target(match["service"], match["number"], match["region"])


def guarded(name: str, check: Callable[[], tuple[bool, str]]) -> Result:
    """One check; an HTTP or API error is that check's failure, reported, never a crash."""
    try:
        ok, detail = check()
    except (httpx.HTTPError, GoogleAPIError, GoogleAuthError, ValueError) as exc:
        return Result(name, False, f"{type(exc).__name__}: {exc}")
    return Result(name, ok, detail)


def http_checks(clients: Clients, cfg: Smoke) -> list[Result]:
    def health() -> tuple[bool, str]:
        response = clients.http.get("/health")
        return response.status_code == httpx.codes.OK, f"HTTP {response.status_code}"

    def root() -> tuple[bool, str]:
        response = clients.http.get("/")
        found = cfg.root_marker.lower() in response.text.lower()
        return response.is_success and found, f"HTTP {response.status_code}, marker found={found}"

    def api_config() -> tuple[bool, str]:
        response = clients.http.get("/api/config")
        body = response.json()  # ValueError on a body that is not JSON: a failed check
        return response.is_success and isinstance(body, dict), f"HTTP {response.status_code}"

    return [
        guarded("GET /health is 200", health),
        guarded("GET / serves the site", root),
        guarded("GET /api/config is a JSON object", api_config),
    ]


def cloud_checks(clients: Clients, target: Target, cfg: Smoke) -> list[Result]:
    timeout = cfg.http_timeout_s

    @functools.cache
    def service() -> run_v2.Service:
        return clients.services.get_service(
            name=target.resource("services", target.service), timeout=timeout
        )

    @functools.cache  # one read per run; an error is not cached, so each check reports it
    def task() -> run_v2.TaskTemplate:
        job = clients.jobs.get_job(name=target.resource("jobs", JOB_NAME), timeout=timeout)
        return job.template.template

    def max_instances() -> tuple[bool, str]:
        count = service().template.scaling.max_instance_count
        return count == cfg.expected_max_instances, f"max_instance_count={count}"

    def cpu_idle() -> tuple[bool, str]:
        idle = service().template.containers[0].resources.cpu_idle
        return idle is True, f"cpu_idle={idle}"

    def job_timeout() -> tuple[bool, str]:
        value = task().timeout
        return value == timedelta(seconds=cfg.expected_job_timeout_s), f"timeout={value}"

    def job_retries() -> tuple[bool, str]:
        template = task()
        if "max_retries" not in template:  # unset means the API default of 3 (F29)
            return False, "max_retries not set"
        return (
            template.max_retries == cfg.expected_job_max_retries,
            f"max_retries={template.max_retries}",
        )

    def ttl_active() -> tuple[bool, str]:
        field = clients.admin.get_field(
            name=f"projects/{target.number}/{TTL_FIELD}", timeout=timeout
        )
        state = TtlState(field.ttl_config.state)
        # Terraform does not wait for TTL (skip_wait); enabling takes ten minutes or more, so
        # CREATING right after a first deploy is pending, not broken.
        pending = " (pending: enabling takes 10+ min)" if state == TtlState.CREATING else ""
        return state in {TtlState.ACTIVE, TtlState.CREATING}, f"state={state.name}{pending}"

    return [
        guarded("service max instances", max_instances),
        guarded("service cpu_idle", cpu_idle),
        guarded("job timeout", job_timeout),
        guarded("job max retries", job_retries),
        guarded("orders TTL active", ttl_active),
    ]


def run_all(clients: Clients, target: Target, cfg: Smoke) -> list[Result]:
    return http_checks(clients, cfg) + cloud_checks(clients, target, cfg)


def say(message: str) -> None:
    sys.stdout.write(f"{message}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Outside-in checks of the live beta.")
    parser.add_argument("--url", required=True, help="the service URL (F61 shape)")
    url = parser.parse_args(argv).url
    try:
        target = parse(url)
    except ValueError as exc:
        say(f"smoke: {exc}")
        return EXIT_ERROR
    cfg = load_cloud().smoke
    with httpx.Client(base_url=target.base_url, timeout=cfg.http_timeout_s) as http:
        try:
            clients = Clients(
                http=http,
                services=run_v2.ServicesClient(),
                jobs=run_v2.JobsClient(),
                admin=firestore_admin_v1.FirestoreAdminClient(),
            )
        except GoogleAuthError as exc:
            say(
                f"FAIL credentials: {type(exc).__name__}; run gcloud auth application-default login"
            )
            return EXIT_FOUND
        results = run_all(clients, target, cfg)
    for result in results:
        say(f"{'PASS' if result.ok else 'FAIL'} {result.name}: {result.detail}")
    return EXIT_CLEAN if all(r.ok for r in results) else EXIT_FOUND


if __name__ == "__main__":
    sys.exit(main())
