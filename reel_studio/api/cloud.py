"""The Cloud Run composition root (TIER=cloud, MAIN-NEXT task 2): Cloud Storage, the Firestore
order store, the reel-editor job and Resend behind the same routes as the laptop.

`google_clients` builds the real Google and Resend clients from Application Default Credentials
(the service's own account on Cloud Run); `cloud_adapters` wires them into the ports, so tests
hand it fakes. Client arguments not set here stay at the library defaults: ADC credentials, the
global endpoints (the job's full name carries its region) and gRPC for Cloud Run (doc ledger:
google-cloud-storage 3.17.0, google-cloud-run 0.16.2). The adapters it imports load the Google
client libraries, so importing reel_studio.api.main loads them on the laptop too (api extra).
"""

import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from reel_studio.adapters import mailer_smtp
from reel_studio.adapters.gcp_launcher import GcpLauncher, JobsClient
from reel_studio.adapters.gcp_storage import (
    AdcIdentity,
    Bucket,
    GcpStorage,
    IdentitySource,
    SessionCanceller,
    StorageConfig,
    storage_retry,
)
from reel_studio.adapters.resend_mailer import Backoff, Email, ResendConfig, ResendMailer
from reel_studio.api.deps import ApiDeps
from reel_studio.core import config as config_models
from reel_studio.core.config import Config, load_cloud
from reel_studio.core.constants import RESEND_API_BASE
from reel_studio.core.ports import Clock, OrderStore, PaymentGateway, Record
from reel_studio.settings import RuntimeSettings, WebSettings


@dataclass(frozen=True)
class Process:
    """What a process reads once at start: its settings, the config and the clock."""

    settings: WebSettings
    runtime: RuntimeSettings
    config: Config
    clock: Clock


@dataclass(frozen=True)
class Budget:
    """How long one outside call may take. reel-api answers inside Cloud Run's 30 s request
    timeout with no CPU after the response (F90), so it gets the request budget; the editor job
    has an hour and gets the full one (config/cloud.toml)."""

    call_timeout_s: float  # one Cloud Storage, Cloud Run or session-cancel call
    retry_deadline_s: float  # Cloud Storage's retries, all attempts together
    resend_timeout_s: float
    resend_retries: int
    resend_backoff_s: float

    @classmethod
    def request(cls, cloud: config_models.Cloud) -> "Budget":
        return cls(
            cloud.gcp.request_timeout_s,
            cloud.gcp.request_retry_deadline_s,
            cloud.resend.request_timeout_s,
            cloud.resend.request_retries,
            cloud.resend.backoff_s,
        )

    @classmethod
    def job(cls, cloud: config_models.Cloud) -> "Budget":
        return cls(
            cloud.gcp.call_timeout_s,
            cloud.gcp.retry_deadline_s,
            cloud.resend.timeout_s,
            cloud.resend.retries,
            cloud.resend.backoff_s,
        )

    def backoff(self) -> Backoff:
        return Backoff(retries=self.resend_retries, base_s=self.resend_backoff_s, sleep=time.sleep)


@dataclass(frozen=True)
class CloudAdapters:
    storage: GcpStorage
    mailer: ResendMailer
    launcher: GcpLauncher


@dataclass(frozen=True)
class CloudClients:
    bucket: Bucket
    identity: IdentitySource
    jobs: JobsClient
    resend: httpx.Client  # base URL and timeout set here, for every Resend call
    sessions: httpx.Client  # cancels resumable upload sessions (F89)


def google_clients(runtime: RuntimeSettings, budget: Budget) -> CloudClients:
    """The real clients; imported here so building them needs the cloud's credentials only
    when TIER=cloud."""
    from google.cloud import run_v2  # noqa: PLC0415 (api extra, Cloud Run only)
    from google.cloud.storage import Client  # noqa: PLC0415 (F88: untyped, overridden)

    values = runtime.cloud()
    return CloudClients(
        bucket=Client(project=runtime.firestore_project).bucket(values.gcs_bucket),
        identity=AdcIdentity(),
        jobs=run_v2.JobsClient(),
        resend=httpx.Client(base_url=RESEND_API_BASE, timeout=budget.resend_timeout_s),
        sessions=httpx.Client(timeout=budget.call_timeout_s),
    )


def resend_render(template: str, data: Record) -> Email:
    """The laptop's templates, as Resend's body wants them (F91)."""
    mail = mailer_smtp.render(template, data)
    return Email(subject=mail.subject, html=mail.html, text=mail.text)


def link_email_worst_case_s(budget: Budget) -> float:
    """Every attempt timing out, plus the waits between them."""
    attempts = budget.resend_retries + 1
    return attempts * budget.resend_timeout_s + budget.backoff().total_wait_s()


def origin(site_url: str) -> str:
    """The browser's Origin header for the site: scheme and host, no path (F32)."""
    parts = urlsplit(site_url)
    return f"{parts.scheme}://{parts.netloc}"


def cloud_adapters(
    runtime: RuntimeSettings,
    cloud: config_models.Cloud,
    clients: CloudClients,
    orders: OrderStore,
    budget: Budget,
) -> CloudAdapters:
    """The Storage, Mailer and Launcher ports over the cloud clients, for reel-api and the
    editor job alike; only the budget differs."""
    values = runtime.cloud()
    storage = GcpStorage(
        clients.bucket,
        clients.identity,
        StorageConfig(
            origin=origin(runtime.site_url),
            timeout_s=budget.call_timeout_s,
            retry=storage_retry(cloud.gcp, budget.retry_deadline_s),
            signed_url_max_minutes=cloud.gcp.signed_url_max_minutes,
        ),
        cancel=SessionCanceller(clients.sessions),
    )
    mailer = ResendMailer(
        clients.resend,
        ResendConfig(api_key=values.resend_sending_key, sender=runtime.mail_from),
        resend_render,
        budget.backoff(),
    )
    launcher = GcpLauncher(
        clients.jobs, orders, job=values.editor_job, timeout_s=budget.call_timeout_s
    )
    return CloudAdapters(storage, mailer, launcher)


def build_cloud_deps(
    process: Process,
    *,
    orders: OrderStore,
    clients: CloudClients,
    payments: PaymentGateway | None,
) -> ApiDeps:
    cloud = load_cloud()
    adapters = cloud_adapters(process.runtime, cloud, clients, orders, Budget.request(cloud))
    return ApiDeps(
        orders=orders,
        storage=adapters.storage,
        local_storage=None,  # browsers upload straight to the bucket
        mailer=adapters.mailer,
        payments=payments,
        clock=process.clock,
        config=process.config,
        settings=process.settings,
        runtime=process.runtime,
        voice_available=process.settings.voice_available,
        web_dist=process.settings.web_dist,
        launcher=adapters.launcher,
    )
