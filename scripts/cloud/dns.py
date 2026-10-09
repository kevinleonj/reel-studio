"""`make dns`: the Resend sending domain, its records in Cloudflare, and a sending-only key.

docs/INFRA.md §3 and D56: create the domain in Resend (region eu-west-1), add the returned
records in Cloudflare as DNS-only, ask Resend to verify and wait, then create a sending-only key
for that domain and write it straight to Secret Manager. Uses RESEND_API_KEY (full access,
laptop only) and CLOUDFLARE_API_TOKEN. Safe to run twice: an existing domain, record or key
is kept (a key's token is only shown at creation, so an existing key is never re-pushed).
"""

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from pydantic import SecretStr

from reel_studio.adapters.resend_mailer import Backoff
from reel_studio.core.config import load_cloud
from reel_studio.settings import CloudSettings
from scripts.cloud._shell import CommandError, GcloudSecrets, SecretStore, run, say

RESEND_API = "https://api.resend.com"  # hardcode-ok: vendor base URL (doc ledger: resend)
CLOUDFLARE_API = "https://api.cloudflare.com/client/v4"  # hardcode-ok: vendor base URL (doc ledger)
SENDING_KEY_SECRET_ID = "resend-api-key"  # noqa: S105 - container name (infra/bootstrap)
VERIFIED = "verified"  # Resend domain status once DNS checks pass
FAILED = "failed"  # terminal: Resend gave up on the records


class DnsError(Exception):
    """An API refused or the domain did not verify in time."""


@dataclass(frozen=True)
class Api:
    """One REST API: an httpx client (base URL, auth, timeout) and its retry policy."""

    client: httpx.Client
    backoff: Backoff

    def call(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, object] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, object]:
        """Bounded retries on timeouts, 429 and 5xx; returns the JSON body."""
        problem = ""
        for attempt in range(self.backoff.retries + 1):
            self.backoff.wait(attempt)
            try:
                response = self.client.request(method, path, json=body, params=params)
            except httpx.TransportError as exc:
                problem = type(exc).__name__
                continue
            if response.is_success:
                data: dict[str, object] = response.json()
                return data
            problem = f"HTTP {response.status_code}"
            transient = response.status_code == httpx.codes.TOO_MANY_REQUESTS
            if not transient and not response.is_server_error:
                break
        raise DnsError(f"{method} {path} failed: {problem}")


@dataclass(frozen=True)
class Apis:
    resend: Api
    cloudflare: Api
    sleep: Callable[[float], None]


@dataclass(frozen=True)
class Settings:
    region: str
    ttl: int
    poll_s: float
    timeout_s: float
    key_name: str


def items(body: object, key: str) -> list[dict[str, object]]:
    """The list under `key`; any other shape stops the run (an existence check must not
    silently read "absent" and create a duplicate)."""
    value = body.get(key) if isinstance(body, dict) else None
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise DnsError(f"unexpected response shape: no list under {key!r}")
    return value


def qualified(name: str, domain: str, zone: str) -> str:
    """Full record name for Cloudflare. Resend's apex example gives names relative to the domain
    (F407); for a subdomain it may give them relative to the zone (`send.reels`). Both map to
    the same full name; a name already ending in the domain is kept."""
    if name == domain or name.endswith(f".{domain}"):
        return name
    sub = domain.removesuffix(f".{zone}")
    if sub != domain and (name == sub or name.endswith(f".{sub}")):
        return f"{name}.{zone}"
    return f"{name}.{domain}"


def unquoted(value: str) -> str:
    return value[1:-1] if len(value) > 1 and value[0] == value[-1] == '"' else value


def ensure_domain(apis: Apis, domain: str, region: str) -> dict[str, object]:
    for found in items(apis.resend.call("GET", "/domains"), "data"):
        if found.get("name") == domain:
            say(f"dns: Resend domain {domain} exists")
            return apis.resend.call("GET", f"/domains/{found['id']}")
    created = apis.resend.call("POST", "/domains", body={"name": domain, "region": region})
    say(f"dns: Resend domain {domain} created in {region}")
    return created


def find_zone(apis: Apis, domain: str) -> tuple[str, str]:
    """(zone id, zone name) of the closest Cloudflare zone holding `domain`."""
    labels = domain.split(".")
    for start in range(len(labels) - 1):
        candidate = ".".join(labels[start:])
        zones = items(
            apis.cloudflare.call("GET", "/zones", params={"name": candidate}),
            "result",
        )
        if zones:
            return str(zones[0]["id"]), candidate
    raise DnsError(f"no Cloudflare zone found for {domain}")


def ensure_records(
    apis: Apis, zone: tuple[str, str], domain: str, records: list[dict[str, object]], ttl: int
) -> int:
    created = 0
    zone_id, zone_name = zone
    for record in records:
        kind, name = str(record["type"]), qualified(str(record["name"]), domain, zone_name)
        content = unquoted(str(record["value"]))
        path = f"/zones/{zone_id}/dns_records"
        existing = items(
            apis.cloudflare.call("GET", path, params={"type": kind, "name": name}),
            "result",
        )
        if any(unquoted(str(r.get("content", ""))) == content for r in existing):
            continue
        body: dict[str, object] = {
            "type": kind,
            "name": name,
            "content": content,
            "ttl": ttl,
            "proxied": False,
        }
        if "priority" in record:
            body["priority"] = record["priority"]
        apis.cloudflare.call("POST", path, body=body)
        created += 1
    say(f"dns: {created} Cloudflare record(s) added, {len(records) - created} already present")
    return created


def wait_verified(
    apis: Apis, domain_id: str, settings: Settings, clock: Callable[[], float]
) -> None:
    started, asked = clock(), False
    while True:
        status = str(apis.resend.call("GET", f"/domains/{domain_id}").get("status"))
        if status == VERIFIED:
            say("dns: domain verified")
            return
        if status == FAILED and asked:
            raise DnsError("Resend marked the domain failed; check the records in Cloudflare")
        if not asked:
            apis.resend.call("POST", f"/domains/{domain_id}/verify")
            asked = True
        if clock() - started >= settings.timeout_s:
            raise DnsError(f"domain not verified after {settings.timeout_s} s, status {status}")
        apis.sleep(settings.poll_s)


def ensure_sending_key(apis: Apis, domain_id: str, name: str, store: SecretStore) -> bool:
    """The token is shown only at creation: the container must exist first, and an existing
    key without a stored value stops the run instead of reporting success."""
    for key in items(apis.resend.call("GET", "/api-keys"), "data"):
        if key.get("name") == name:
            if not store.has_value(SENDING_KEY_SECRET_ID):
                raise DnsError(
                    f"sending key {name} exists but {SENDING_KEY_SECRET_ID} holds no value;"
                    " delete the key in the Resend dashboard and run make dns again"
                )
            say(f"dns: sending key {name} exists and its token is stored")
            return False
    store.ready(SENDING_KEY_SECRET_ID)
    created = apis.resend.call(
        "POST",
        "/api-keys",
        body={"name": name, "permission": "sending_access", "domain_id": domain_id},
    )
    store.put(SENDING_KEY_SECRET_ID, SecretStr(str(created["token"])))
    say(f"dns: sending key {name} created and stored")
    return True


def configure(
    apis: Apis, domain: str, settings: Settings, store: SecretStore, clock: Callable[[], float]
) -> None:
    found = ensure_domain(apis, domain, settings.region)
    domain_id = str(found["id"])
    ensure_records(apis, find_zone(apis, domain), domain, items(found, "records"), settings.ttl)
    wait_verified(apis, domain_id, settings, clock)
    ensure_sending_key(apis, domain_id, settings.key_name, store)


def main() -> int:
    env = CloudSettings()
    cfg = load_cloud()
    timeout = httpx.Timeout(cfg.dns.http_timeout_s)
    resend = httpx.Client(
        base_url=RESEND_API,
        timeout=timeout,
        headers={"Authorization": f"Bearer {env.resend_api_key.get_secret_value()}"},
    )
    cloudflare = httpx.Client(
        base_url=CLOUDFLARE_API,
        timeout=timeout,
        headers={"Authorization": f"Bearer {env.cloudflare_api_token.get_secret_value()}"},
    )
    backoff = Backoff(cfg.dns.http_retries, cfg.dns.backoff_s, time.sleep)
    apis = Apis(Api(resend, backoff), Api(cloudflare, backoff), time.sleep)
    settings = Settings(
        cfg.dns.resend_region,
        cfg.dns.record_ttl,
        cfg.dns.verify_poll_s,
        cfg.dns.verify_timeout_s,
        cfg.dns.sending_key_name,
    )
    try:
        configure(
            apis,
            env.email_domain,
            settings,
            GcloudSecrets(run, env.gcp_project, cfg.gcloud.timeout_s),
            time.monotonic,
        )
    except (DnsError, CommandError, ValueError) as exc:
        say(f"dns: {exc}")
        return 1
    finally:
        resend.close()
        cloudflare.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
