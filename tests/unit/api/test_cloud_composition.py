"""The Cloud Run composition root (TIER=cloud): Cloud Storage, Resend and the editor job behind
the same routes, every Google and Resend client replaced by its fake."""

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from google.api_core import exceptions as google_exceptions

from reel_studio.adapters.gcp_launcher import ORDER_ID_ENV, GcpLauncher
from reel_studio.adapters.gcp_storage import GcpStorage, SigningIdentity
from reel_studio.adapters.resend_mailer import ResendMailer
from reel_studio.api import cloud, main
from reel_studio.api.app import create_app
from reel_studio.api.cloud import (
    Budget,
    CloudClients,
    Process,
    build_cloud_deps,
    link_email_worst_case_s,
)
from reel_studio.api.deps import ApiDeps
from reel_studio.core.config import load, load_cloud
from reel_studio.core.errors import DeliveryFailed, OrderBusy
from reel_studio.settings import RuntimeSettings, WebSettings
from tests.conftest import MakeSettings
from tests.fakes.clock import FrozenClock
from tests.fakes.gcp import FakeBucket, FakeJobsClient
from tests.fakes.orders import FakeOrders
from tests.unit.api.conftest import LIMITS, SITE_FILES, START
from tests.unit.infra.test_env_contract import terraform_locals

JOB = "projects/test-project/locations/test-region/jobs/reel-editor"
RESEND = "https://resend.test"
SETTINGS = {"style": "recipe", "length_s": 30, "text_lang": "en", "keep_voice": False}
CLOUD = {
    "tier": "cloud",
    "smtp_host": None,
    "smtp_port": None,
    "data_dir": None,
    "gcs_bucket": "reel-studio-media-test",
    "editor_job": JOB,
    "resend_sending_key": "test-sending-key",
}


class Sent:
    """Resend's POST /emails, answered 200; the bodies are kept for the assertions."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, object]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "email-1"})


class Broken(Sent):
    """A mail transport that fails with something other than an HTTP answer."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        raise RuntimeError("mail transport fell over")


def clients(bucket: FakeBucket, jobs: FakeJobsClient, sent: Sent) -> CloudClients:
    identity = SigningIdentity(email="reel-api@test.iam.gserviceaccount.com", token="t")
    return CloudClients(
        bucket=bucket,
        identity=lambda: identity,
        jobs=jobs,
        resend=httpx.Client(base_url=RESEND, transport=httpx.MockTransport(sent)),
        sessions=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(499))),
    )


def settings(tmp_path: Path, make_settings: MakeSettings) -> tuple[WebSettings, RuntimeSettings]:
    dist = tmp_path / "dist"
    for name, body in SITE_FILES.items():
        (dist / name).parent.mkdir(parents=True, exist_ok=True)
        (dist / name).write_text(body)
    web = make_settings(WebSettings, payments="off", web_dist=dist)
    runtime = make_settings(RuntimeSettings, **CLOUD)
    assert isinstance(web, WebSettings)
    assert isinstance(runtime, RuntimeSettings)
    return web, runtime


def cloud_deps(
    tmp_path: Path, make_settings: MakeSettings, fakes: tuple[FakeBucket, FakeJobsClient, Sent]
) -> ApiDeps:
    web, runtime = settings(tmp_path, make_settings)
    clock = FrozenClock(START)
    process = Process(web, runtime, load(), clock)
    orders = FakeOrders(clock, LIMITS)
    return build_cloud_deps(process, orders=orders, clients=clients(*fakes), payments=None)


def checkout(client: TestClient, email: str) -> tuple[str, dict[str, str]]:
    body = {"settings": {**SETTINGS, "chips": [], "note": ""}, "code": "", "email": email}
    order_url = client.post("/api/checkout", json=body).json()["order_url"]
    order_id, token = order_url.removeprefix("/o/").split("#t=")
    return order_id, {"X-Order-Token": token}


def upload(client: TestClient, bucket: FakeBucket, order_id: str, headers: dict[str, str]) -> None:
    files = {"files": [{"name": "a.mp4", "size": 4, "type": "video/mp4"}]}
    target = client.post(f"/api/orders/{order_id}/uploads", json=files, headers=headers).json()
    bucket.complete(target["targets"][0]["upload_url"], b"clip")


def test_the_cloud_root_builds_the_cloud_adapters(
    tmp_path: Path, make_settings: MakeSettings
) -> None:
    deps = cloud_deps(tmp_path, make_settings, (FakeBucket(), FakeJobsClient(), Sent()))

    assert isinstance(deps.storage, GcpStorage)
    assert isinstance(deps.mailer, ResendMailer)
    assert isinstance(deps.launcher, GcpLauncher)
    assert deps.local_storage is None  # no chunk endpoint: browsers upload to the bucket


def test_an_order_goes_from_checkout_to_a_started_editor_job(
    tmp_path: Path, make_settings: MakeSettings
) -> None:
    bucket, jobs, sent = FakeBucket(), FakeJobsClient(), Sent()
    deps = cloud_deps(tmp_path, make_settings, (bucket, jobs, sent))
    client = TestClient(create_app(deps))

    order_id, headers = checkout(client, "friend@example.test")
    upload(client, bucket, order_id, headers)
    started = client.post(f"/api/orders/{order_id}/start", headers=headers)

    assert started.status_code == 200
    assert len(sent.bodies) == 1  # the link email went through Resend
    [run] = jobs.calls
    request = run["request"]
    assert request.name == JOB  # type: ignore[attr-defined]
    [override] = request.overrides.container_overrides  # type: ignore[attr-defined]
    assert {e.name: e.value for e in override.env}[ORDER_ID_ENV] == order_id
    doc = deps.orders.get(order_id)
    assert doc is not None and doc["status"] == "running"


def test_a_job_that_cannot_start_fails_the_order_and_frees_its_slot(
    tmp_path: Path, make_settings: MakeSettings
) -> None:
    unavailable = google_exceptions.ServiceUnavailable("down")  # type: ignore[no-untyped-call]
    bucket, jobs = FakeBucket(), FakeJobsClient(raises=unavailable)
    deps = cloud_deps(tmp_path, make_settings, (bucket, jobs, Sent()))
    client = TestClient(create_app(deps))

    order_id, headers = checkout(client, "")
    upload(client, bucket, order_id, headers)

    assert client.post(f"/api/orders/{order_id}/start", headers=headers).status_code == 200
    doc = deps.orders.get(order_id)
    assert doc is not None and doc["status"] == "failed"
    assert deps.orders.next_queued() is None
    assert order_id not in deps.orders.capacity["slots"]  # type: ignore[attr-defined]


def test_a_failure_notice_that_breaks_never_breaks_start(
    tmp_path: Path, make_settings: MakeSettings
) -> None:
    """The launch failed and so does the mail transport, not with DeliveryFailed: the order is
    still failed and Start still answers (notify.launch_failed's catch-all, review S1)."""
    unavailable = google_exceptions.ServiceUnavailable("down")  # type: ignore[no-untyped-call]
    bucket, jobs = FakeBucket(), FakeJobsClient(raises=unavailable)
    deps = cloud_deps(tmp_path, make_settings, (bucket, jobs, Broken()))
    client = TestClient(create_app(deps))
    order_id, headers = checkout(client, "")
    upload(client, bucket, order_id, headers)

    assert client.post(f"/api/orders/{order_id}/start", headers=headers).status_code == 200
    doc = deps.orders.get(order_id)
    assert doc is not None and doc["status"] == "failed"


def test_a_start_retried_after_busy_still_launches(
    tmp_path: Path, make_settings: MakeSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first Start queues, then take_slot runs out of attempts (503 busy); the retry finds
    the order queued and must launch it, or nothing ever does in the cloud (review W1)."""
    bucket, jobs = FakeBucket(), FakeJobsClient()
    deps = cloud_deps(tmp_path, make_settings, (bucket, jobs, Sent()))
    client = TestClient(create_app(deps))
    order_id, headers = checkout(client, "")
    upload(client, bucket, order_id, headers)
    take_slot = deps.orders.take_slot
    busy = [OrderBusy("take_slot")]

    def once_busy(order: str) -> bool:
        if busy:
            raise busy.pop()
        return take_slot(order)

    monkeypatch.setattr(deps.orders, "take_slot", once_busy)

    assert client.post(f"/api/orders/{order_id}/start", headers=headers).status_code == 503
    assert client.post(f"/api/orders/{order_id}/start", headers=headers).status_code == 200
    assert len(jobs.calls) == 1
    doc = deps.orders.get(order_id)
    assert doc is not None and doc["status"] == "running"


def test_a_cloud_outage_answers_503_cloud_unavailable(
    tmp_path: Path, make_settings: MakeSettings
) -> None:
    bucket = FakeBucket()
    deps = cloud_deps(tmp_path, make_settings, (bucket, FakeJobsClient(), Sent()))
    client = TestClient(create_app(deps))
    order_id, headers = checkout(client, "")
    bucket.raises = google_exceptions.ServiceUnavailable("down")  # type: ignore[no-untyped-call]
    files = {"files": [{"name": "a.mp4", "size": 1, "type": "video/mp4"}]}

    answer = client.post(f"/api/orders/{order_id}/uploads", json=files, headers=headers)

    assert (answer.status_code, answer.json()) == (503, {"error": "cloud_unavailable"})


def test_create_builds_the_cloud_app_when_tier_is_cloud(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    environment = {
        "TIER": "cloud",
        "PAYMENTS": "off",
        "SITE_URL": "https://reel-api.test",
        "MAIL_FROM": "reels@example.test",
        "KEVIN_ALERT_EMAIL": "kevin@example.test",
        "FIRESTORE_PROJECT": "test-project",
        "GCS_BUCKET": "reel-studio-media-test",
        "EDITOR_JOB": JOB,
        "RESEND_SENDING_KEY": "test-sending-key",
        "WEB_DIST": str(tmp_path),
        "VOICE_AVAILABLE": "true",
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    built: list[str] = []

    def fake_clients(runtime: RuntimeSettings, budget: Budget) -> CloudClients:
        built.append(runtime.cloud().gcs_bucket)
        assert budget == Budget.request(load_cloud())  # reel-api's, not the editor job's
        return clients(FakeBucket(), FakeJobsClient(), Sent())

    def fake_orders(_runtime: object, _config: object, clock: FrozenClock) -> FakeOrders:
        return FakeOrders(clock, LIMITS)

    monkeypatch.setattr(main, "google_clients", fake_clients)
    monkeypatch.setattr(main, "firestore_orders", fake_orders)

    assert TestClient(main.create()).get("/health").text == "ok"
    assert built == ["reel-studio-media-test"]


def api_request_timeout_s() -> float:
    return float(str(terraform_locals()["api_request_timeout"]).strip('"').removesuffix("s"))


def retried_call_worst_case_s(budget: Budget) -> float:
    """api_core's deadline only gates when an attempt may start: the last one may still run a
    whole call timeout after it (task 2 review round 2, measured)."""
    return budget.retry_deadline_s + budget.call_timeout_s


def test_the_link_email_and_one_call_fit_inside_one_api_request() -> None:
    """cloud.md W7: 4 attempts of 15 s exceed Cloud Run's 30 s request timeout, and Cloud Run
    gives no CPU after the response (F90). The webhook sends the link email after a Firestore
    call. Stripe's own calls are not in this sum (config/limits.toml [stripe])."""
    budget = Budget.request(load_cloud())

    assert link_email_worst_case_s(budget) + budget.call_timeout_s < api_request_timeout_s()


def test_start_lists_the_bucket_and_launches_inside_one_api_request() -> None:
    budget = Budget.request(load_cloud())

    assert retried_call_worst_case_s(budget) + budget.call_timeout_s < api_request_timeout_s()


def test_reel_api_wires_the_request_budget_into_every_adapter(
    tmp_path: Path, make_settings: MakeSettings
) -> None:
    """Pinned at the call sites, not only in the arithmetic (task 2 review round 2, W1)."""
    deps = cloud_deps(tmp_path, make_settings, (FakeBucket(), FakeJobsClient(), Sent()))
    budget = Budget.request(load_cloud())
    storage: Any = deps.storage
    launcher: Any = deps.launcher
    mailer: Any = deps.mailer

    assert storage._cfg.timeout_s == budget.call_timeout_s
    assert storage._cfg.retry._timeout == budget.retry_deadline_s
    assert launcher._timeout_s == budget.call_timeout_s
    assert mailer._backoff.retries == budget.resend_retries


@pytest.mark.parametrize("make_budget", [Budget.request, Budget.job])
def test_both_http_clients_carry_the_budget_timeouts(make_budget: Callable[..., Budget]) -> None:
    """A client built without a timeout falls back to httpx's 5 s default (review warning)."""
    budget = make_budget(load_cloud())

    resend, sessions = cloud.http_clients(budget)

    assert resend.timeout == httpx.Timeout(budget.resend_timeout_s)
    assert sessions.timeout == httpx.Timeout(budget.call_timeout_s)
    assert resend.base_url == httpx.URL(cloud.RESEND_API_BASE)


def test_reel_api_mails_with_its_request_budget(
    make_settings: MakeSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wiring, not only the numbers: two attempts, one wait (review W4)."""
    attempts: list[httpx.Request] = []

    def failing(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        return httpx.Response(500)

    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", sleeps.append)  # the Backoff cloud_adapters builds
    runtime = make_settings(RuntimeSettings, **CLOUD)
    assert isinstance(runtime, RuntimeSettings)
    fakes = clients(FakeBucket(), FakeJobsClient(), Sent())
    resend = httpx.Client(base_url=RESEND, transport=httpx.MockTransport(failing))
    budget = Budget.request(load_cloud())
    adapters = cloud.cloud_adapters(
        runtime,
        load_cloud(),
        replace(fakes, resend=resend),
        FakeOrders(FrozenClock(START), LIMITS),
        budget,
    )

    with pytest.raises(DeliveryFailed):
        adapters.mailer.send(
            "kevin",
            "kevin@example.test",
            {"order_id": "o", "status": "s", "stage": "x", "code": "c"},
        )

    assert len(attempts) == budget.resend_retries + 1 == 2
    assert sleeps == [load_cloud().resend.backoff_s]


def test_the_site_origin_has_no_path() -> None:
    assert cloud.origin("https://reel-api-1.europe-west1.run.app/") == (
        "https://reel-api-1.europe-west1.run.app"
    )
