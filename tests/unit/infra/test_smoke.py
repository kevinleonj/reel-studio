"""scripts/smoke.py (`make smoke URL=...`): outside-in checks of the live beta (docs/INFRA.md §4).

Written, not run against a URL in phase A. HTTP goes through httpx.MockTransport; the Cloud Run
and Firestore admin clients are fakes that return real run_v2 / firestore_admin_v1 messages.
"""

from dataclasses import dataclass, field
from datetime import timedelta

import httpx
import pytest
from google.api_core import exceptions as google_exceptions
from google.cloud import firestore_admin_v1, run_v2

from reel_studio.core import config
from scripts import smoke

URL = "https://reel-api-123456789012.europe-west1.run.app"
State = firestore_admin_v1.Field.TtlConfig.State


def site(
    health: int = 200, root: str = "<!doctype html><html>", api: object | None = None
) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(health, text="ok")
        if request.url.path == "/":
            return httpx.Response(200, text=root)
        if request.url.path == "/api/config":
            return httpx.Response(200, json=api if api is not None else {"styles": {}})
        return httpx.Response(404)

    return httpx.MockTransport(handle)


@dataclass
class FakeServices:
    max_instances: int = 2
    cpu_idle: bool = True
    names: list[str] = field(default_factory=list)

    def get_service(self, *, name: str, timeout: float) -> run_v2.Service:
        self.names.append(name)
        container = run_v2.Container(resources=run_v2.ResourceRequirements(cpu_idle=self.cpu_idle))
        scaling = run_v2.RevisionScaling(max_instance_count=self.max_instances)
        return run_v2.Service(
            template=run_v2.RevisionTemplate(scaling=scaling, containers=[container])
        )


@dataclass
class FakeJobs:
    timeout_s: int = 3600
    retries: int | None = 0
    names: list[str] = field(default_factory=list)

    def get_job(self, *, name: str, timeout: float) -> run_v2.Job:
        self.names.append(name)
        task = run_v2.TaskTemplate(timeout=timedelta(seconds=self.timeout_s))
        if self.retries is not None:
            task.max_retries = self.retries
        return run_v2.Job(template=run_v2.ExecutionTemplate(template=task))


@dataclass
class FakeAdmin:
    state: int = State.ACTIVE
    raises: Exception | None = None
    names: list[str] = field(default_factory=list)

    def get_field(self, *, name: str, timeout: float) -> firestore_admin_v1.Field:
        self.names.append(name)
        if self.raises is not None:
            raise self.raises
        return firestore_admin_v1.Field(
            ttl_config=firestore_admin_v1.Field.TtlConfig(state=self.state)
        )


def check(transport: httpx.MockTransport, **fakes: object) -> list[smoke.Result]:
    target = smoke.parse(URL)
    clients = smoke.Clients(
        http=httpx.Client(base_url=target.base_url, transport=transport),
        services=fakes.get("services", FakeServices()),  # type: ignore[arg-type]
        jobs=fakes.get("jobs", FakeJobs()),  # type: ignore[arg-type]
        admin=fakes.get("admin", FakeAdmin()),  # type: ignore[arg-type]
    )
    return smoke.run_all(clients, target, config.load_cloud().smoke)


def failed(results: list[smoke.Result]) -> list[str]:
    return [r.name for r in results if not r.ok]


def test_url_gives_service_project_number_and_region() -> None:
    target = smoke.parse(URL + "/")

    assert (target.service, target.number, target.region) == (
        "reel-api",
        "123456789012",
        "europe-west1",
    )
    assert target.base_url == URL


@pytest.mark.parametrize(
    "url", ["http://reel-api-1.europe-west1.run.app", "https://example.test", ""]
)
def test_other_urls_are_refused(url: str) -> None:
    with pytest.raises(ValueError, match=r"run\.app"):
        smoke.parse(url)


def test_healthy_deploy_passes_every_check() -> None:
    services, jobs, admin = FakeServices(), FakeJobs(), FakeAdmin()

    results = check(site(), services=services, jobs=jobs, admin=admin)

    assert failed(results) == []
    assert len(results) == 8
    assert services.names == ["projects/123456789012/locations/europe-west1/services/reel-api"]
    assert jobs.names == ["projects/123456789012/locations/europe-west1/jobs/reel-editor"]
    assert admin.names == [
        "projects/123456789012/databases/(default)/collectionGroups/orders/fields/expires_at"
    ]


@pytest.mark.parametrize(
    ("kwargs", "name"),
    [
        ({"transport": site(health=503)}, "GET /health is 200"),
        ({"transport": site(root="nothing here")}, "GET / serves the site"),
        ({"transport": site(api=["not", "an", "object"])}, "GET /api/config is a JSON object"),
        ({"services": FakeServices(max_instances=5)}, "service max instances"),
        ({"services": FakeServices(cpu_idle=False)}, "service cpu_idle"),
        ({"jobs": FakeJobs(timeout_s=600)}, "job timeout"),
        ({"jobs": FakeJobs(retries=None)}, "job max retries"),
        ({"jobs": FakeJobs(retries=3)}, "job max retries"),
        ({"admin": FakeAdmin(state=State.CREATING)}, "orders TTL active"),
    ],
)
def test_each_defect_fails_exactly_its_check(kwargs: dict[str, object], name: str) -> None:
    transport = kwargs.pop("transport", site())

    assert failed(check(transport, **kwargs)) == [name]  # type: ignore[arg-type]


def test_an_api_error_is_a_failed_check_not_a_crash() -> None:
    denied = google_exceptions.PermissionDenied("no access")  # type: ignore[no-untyped-call]

    results = check(site(), admin=FakeAdmin(raises=denied))

    [result] = [r for r in results if not r.ok]
    assert result.name == "orders TTL active"
    assert "PermissionDenied" in result.detail


def test_main_exit_codes(capsys: pytest.CaptureFixture[str]) -> None:
    assert smoke.main(["--url", "https://example.test"]) == smoke.EXIT_ERROR
    assert "run.app" in capsys.readouterr().out
