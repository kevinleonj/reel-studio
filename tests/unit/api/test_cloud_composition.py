"""The Cloud Run composition root (TIER=cloud): Cloud Storage, Resend and the editor job behind
the same routes, every Google and Resend client replaced by its fake."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from google.api_core import exceptions as google_exceptions

from reel_studio.adapters.gcp_launcher import ORDER_ID_ENV, GcpLauncher
from reel_studio.adapters.gcp_storage import GcpStorage, SigningIdentity
from reel_studio.adapters.resend_mailer import ResendMailer
from reel_studio.api import main
from reel_studio.api.app import create_app
from reel_studio.api.cloud import CloudClients, Process, build_cloud_deps, link_email_worst_case_s
from reel_studio.api.deps import ApiDeps
from reel_studio.core.config import load, load_cloud
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

    def fake_clients(runtime: RuntimeSettings, _config: object, **_: object) -> CloudClients:
        built.append(runtime.cloud().gcs_bucket)
        return clients(FakeBucket(), FakeJobsClient(), Sent())

    def fake_orders(_runtime: object, _config: object, clock: FrozenClock) -> FakeOrders:
        return FakeOrders(clock, LIMITS)

    monkeypatch.setattr(main, "google_clients", fake_clients)
    monkeypatch.setattr(main, "firestore_orders", fake_orders)

    assert TestClient(main.create()).get("/health").text == "ok"
    assert built == ["reel-studio-media-test"]


def test_the_link_email_fits_inside_one_api_request() -> None:
    """cloud.md W7: 4 attempts of 15 s exceed Cloud Run's 30 s request timeout, and Cloud Run
    gives no CPU after the response (F90), so the request path gets a budget of its own."""
    timeout = str(terraform_locals()["api_request_timeout"]).strip('"').removesuffix("s")

    assert link_email_worst_case_s(load_cloud().resend) < int(timeout)
