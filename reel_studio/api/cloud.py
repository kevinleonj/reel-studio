"""The Cloud Run composition root (TIER=cloud, MAIN-NEXT task 2): Cloud Storage, the Firestore
order store, the reel-editor job and Resend behind the same routes as the laptop.

`google_clients` builds the real Google and Resend clients from Application Default Credentials
(the service's own account on Cloud Run); `build_cloud_deps` wires them into the adapters, so
tests hand it fakes. Client arguments not set here stay at the library defaults: ADC
credentials, the global endpoints (the job's full name carries its region) and gRPC for Cloud
Run (doc ledger: google-cloud-storage 3.17.0, google-cloud-run 0.16.2).
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
class CloudClients:
    bucket: Bucket
    identity: IdentitySource
    jobs: JobsClient
    resend: httpx.Client  # base URL and timeout set here, for every Resend call
    sessions: httpx.Client  # cancels resumable upload sessions (F89)


def google_clients(runtime: RuntimeSettings, cloud: config_models.Cloud) -> CloudClients:
    """The real clients; imported here so the laptop never loads the Google client libraries."""
    from google.cloud import run_v2  # noqa: PLC0415 (api extra, Cloud Run only)
    from google.cloud.storage import Client  # noqa: PLC0415 (F88: untyped, overridden)

    values = runtime.cloud()
    return CloudClients(
        bucket=Client(project=runtime.firestore_project).bucket(values.gcs_bucket),
        identity=AdcIdentity(),
        jobs=run_v2.JobsClient(),
        resend=httpx.Client(base_url=RESEND_API_BASE, timeout=cloud.resend.request_timeout_s),
        sessions=httpx.Client(timeout=cloud.gcp.call_timeout_s),
    )


def resend_render(template: str, data: Record) -> Email:
    """The laptop's templates, as Resend's body wants them (F91)."""
    mail = mailer_smtp.render(template, data)
    return Email(subject=mail.subject, html=mail.html, text=mail.text)


def link_email_worst_case_s(resend: config_models.Resend) -> float:
    """Every attempt timing out, plus the waits between them (resend_mailer.Backoff)."""
    attempts = resend.request_retries + 1
    waits = sum(resend.backoff_s * 2.0 ** (n - 1) for n in range(1, attempts))
    return attempts * resend.request_timeout_s + waits


def origin(site_url: str) -> str:
    """The browser's Origin header for the site: scheme and host, no path (F32)."""
    parts = urlsplit(site_url)
    return f"{parts.scheme}://{parts.netloc}"


def build_cloud_deps(
    process: Process,
    *,
    orders: OrderStore,
    clients: CloudClients,
    payments: PaymentGateway | None,
) -> ApiDeps:
    cloud = load_cloud()
    values = process.runtime.cloud()
    gcp = cloud.gcp
    storage = GcpStorage(
        clients.bucket,
        clients.identity,
        StorageConfig(
            origin=origin(process.runtime.site_url),
            timeout_s=gcp.call_timeout_s,
            retry=storage_retry(gcp),
            signed_url_max_minutes=gcp.signed_url_max_minutes,
        ),
        cancel=SessionCanceller(clients.sessions),
    )
    mailer = ResendMailer(
        clients.resend,
        ResendConfig(api_key=values.resend_sending_key, sender=process.runtime.mail_from),
        resend_render,
        Backoff(
            retries=cloud.resend.request_retries, base_s=cloud.resend.backoff_s, sleep=time.sleep
        ),
    )
    return ApiDeps(
        orders=orders,
        storage=storage,
        local_storage=None,  # browsers upload straight to the bucket
        mailer=mailer,
        payments=payments,
        clock=process.clock,
        config=process.config,
        settings=process.settings,
        runtime=process.runtime,
        voice_available=process.settings.voice_available,
        web_dist=process.settings.web_dist,
        launcher=GcpLauncher(
            clients.jobs, orders, job=values.editor_job, timeout_s=gcp.call_timeout_s
        ),
    )
