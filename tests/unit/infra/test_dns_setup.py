"""scripts/cloud/dns.py (`make dns`): Resend domain, Cloudflare records, verification, sending key.

Written, not run in phase A. Both APIs are fakes behind httpx.MockTransport that answer in the
documented shapes (doc ledger: resend, cloudflare-dns-rest).
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
import pytest
from pydantic import SecretStr

from reel_studio.adapters.resend_mailer import Backoff
from scripts.cloud import dns
from scripts.cloud._shell import CommandError

DOMAIN = "reels.example.test"
ZONE = "example.test"
RECORDS = [
    {"record": "DKIM", "name": "resend._domainkey", "type": "TXT", "value": "p=KEY"},
    {"record": "SPF", "name": "send", "type": "MX", "value": "feedback.test", "priority": 10},
    {"record": "SPF", "name": "send", "type": "TXT", "value": '"v=spf1 include:ses.test ~all"'},
]


@dataclass
class FakeResend:
    domains: list[dict[str, object]] = field(default_factory=list)
    keys: list[dict[str, object]] = field(default_factory=list)
    statuses: list[str] = field(default_factory=lambda: ["pending", "verified"])
    posted: list[tuple[str, object]] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else {}
        if method == "POST":
            self.posted.append((path, body))
        routes: dict[tuple[str, str], Callable[[dict[str, object]], dict[str, object]]] = {
            ("GET", "/domains"): lambda _: {"object": "list", "data": self.domains},
            ("POST", "/domains"): self.create_domain,
            ("GET", "/domains/dom-1"): lambda _: {
                "id": "dom-1",
                "status": self.next_status(),
                "records": RECORDS,
            },
            ("POST", "/domains/dom-1/verify"): lambda _: {"object": "domain", "id": "dom-1"},
            ("GET", "/api-keys"): lambda _: {"object": "list", "data": self.keys},
            ("POST", "/api-keys"): lambda _: {"id": "key-1", "token": "sending-token-value"},
        }
        route = routes.get((method, path))
        if route is None:
            return httpx.Response(404, json={"name": "not_found"})
        return httpx.Response(200, json=route(body))

    def create_domain(self, body: dict[str, object]) -> dict[str, object]:
        domain = {"id": "dom-1", "name": body["name"], "status": "not_started", "records": RECORDS}
        self.domains.append(domain)
        return domain

    def next_status(self) -> str:
        return self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]


@dataclass
class FakeCloudflare:
    existing: list[dict[str, object]] = field(default_factory=list)
    created: list[dict[str, object]] = field(default_factory=list)
    flaky: int = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.flaky:
            self.flaky -= 1
            return httpx.Response(429, json={"success": False})
        path = request.url.path
        if path == "/zones":
            name = request.url.params["name"]
            result = [{"id": "zone-1", "name": ZONE}] if name == ZONE else []
            return httpx.Response(200, json={"success": True, "result": result})
        if path == "/zones/zone-1/dns_records" and request.method == "GET":
            params = request.url.params
            found = [
                r
                for r in self.existing
                if r["type"] == params["type"] and r["name"] == params["name"]
            ]
            return httpx.Response(200, json={"success": True, "result": found})
        if path == "/zones/zone-1/dns_records" and request.method == "POST":
            record = json.loads(request.content)
            self.created.append(record)
            return httpx.Response(200, json={"success": True, "result": record})
        return httpx.Response(404, json={"success": False})


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def setup(resend: FakeResend, cloudflare: FakeCloudflare, clock: Clock) -> dns.Apis:
    backoff = Backoff(retries=2, base_s=1.0, sleep=clock.sleep)
    resend_client = httpx.Client(
        base_url="https://resend.test", transport=httpx.MockTransport(resend)
    )
    cloudflare_client = httpx.Client(
        base_url="https://cloudflare.test", transport=httpx.MockTransport(cloudflare)
    )
    return dns.Apis(
        resend=dns.Api(resend_client, backoff),
        cloudflare=dns.Api(cloudflare_client, backoff),
        sleep=clock.sleep,
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("send", "send.reels.example.test"),
        ("resend._domainkey", "resend._domainkey.reels.example.test"),
        ("links.reels.example.test", "links.reels.example.test"),
        ("reels.example.test", "reels.example.test"),
        # relative to the zone instead of the domain: the same full names (review W2)
        ("send.reels", "send.reels.example.test"),
        ("resend._domainkey.reels", "resend._domainkey.reels.example.test"),
    ],
)
def test_record_names_are_qualified_once(name: str, expected: str) -> None:
    assert dns.qualified(name, DOMAIN, ZONE) == expected


class FakeStore:
    def __init__(self, *, ready: bool = True, has_value: bool = True) -> None:
        self.is_ready, self.holds = ready, has_value
        self.put_calls: list[tuple[str, str]] = []

    def ready(self, secret_id: str) -> None:
        if not self.is_ready:
            raise CommandError(f"gcloud secrets describe {secret_id} exited 1: NOT_FOUND")

    def has_value(self, secret_id: str) -> bool:
        return self.holds

    def put(self, secret_id: str, value: SecretStr) -> None:
        self.put_calls.append((secret_id, value.get_secret_value()))


SETTINGS = dns.Settings(region="eu-west-1", ttl=1, poll_s=30, timeout_s=600, key_name="sending")


def run_dns(
    resend: FakeResend,
    cloudflare: FakeCloudflare,
    store: FakeStore,
    *,
    domain: str = DOMAIN,
    settings: dns.Settings = SETTINGS,
) -> Clock:
    clock = Clock()
    dns.configure(setup(resend, cloudflare, clock), domain, settings, store, clock.monotonic)
    return clock


def test_first_run_creates_domain_records_and_key() -> None:
    resend, cloudflare, store = FakeResend(), FakeCloudflare(), FakeStore()

    run_dns(resend, cloudflare, store)

    assert ("/domains", {"name": DOMAIN, "region": "eu-west-1"}) in resend.posted
    names = [(r["type"], r["name"]) for r in cloudflare.created]
    assert names == [
        ("TXT", "resend._domainkey.reels.example.test"),
        ("MX", "send.reels.example.test"),
        ("TXT", "send.reels.example.test"),
    ]
    assert all(r["proxied"] is False and r["ttl"] == 1 for r in cloudflare.created)
    assert cloudflare.created[1]["priority"] == 10
    assert cloudflare.created[2]["content"] == "v=spf1 include:ses.test ~all"
    key_body = {"name": "sending", "permission": "sending_access", "domain_id": "dom-1"}
    assert ("/api-keys", key_body) in resend.posted
    assert store.put_calls == [("resend-api-key", "sending-token-value")]


def test_second_run_creates_nothing() -> None:
    resend = FakeResend(
        domains=[{"id": "dom-1", "name": DOMAIN, "status": "verified"}],
        keys=[{"id": "key-1", "name": "sending"}],
        statuses=["verified"],
    )
    cloudflare = FakeCloudflare(
        existing=[
            {"type": "TXT", "name": "resend._domainkey.reels.example.test", "content": '"p=KEY"'},
            {"type": "MX", "name": "send.reels.example.test", "content": "feedback.test"},
            # Cloudflare answers TXT content quoted; the comparison must not create a duplicate
            {
                "type": "TXT",
                "name": "send.reels.example.test",
                "content": '"v=spf1 include:ses.test ~all"',
            },
        ]
    )
    store = FakeStore()

    run_dns(resend, cloudflare, store)

    assert cloudflare.created == []
    assert resend.posted == []  # not even /verify: the domain is already verified
    assert store.put_calls == []


def test_missing_container_stops_before_resend_mints_a_key() -> None:
    resend = FakeResend()

    with pytest.raises(CommandError, match="NOT_FOUND"):
        run_dns(resend, FakeCloudflare(), FakeStore(ready=False))

    assert all(path != "/api-keys" for path, _ in resend.posted)


def test_rerun_after_a_lost_token_stops_with_the_recovery_step() -> None:
    resend = FakeResend(keys=[{"id": "key-1", "name": "sending"}])

    with pytest.raises(dns.DnsError, match="delete the key"):
        run_dns(resend, FakeCloudflare(), FakeStore(has_value=False))


def test_unexpected_list_shape_stops_instead_of_creating_a_duplicate() -> None:
    resend = FakeResend()
    resend.keys = {"keys": []}  # type: ignore[assignment]

    with pytest.raises(dns.DnsError, match="shape"):
        run_dns(resend, FakeCloudflare(), FakeStore())

    assert all(path != "/api-keys" for path, _ in resend.posted)


def test_verification_times_out_with_the_last_status() -> None:
    settings = dns.Settings("eu-west-1", 1, 30, 90, "sending")

    with pytest.raises(dns.DnsError, match="pending"):
        run_dns(FakeResend(statuses=["pending"]), FakeCloudflare(), FakeStore(), settings=settings)


def test_failed_verification_stops_at_once() -> None:
    with pytest.raises(dns.DnsError, match="failed"):
        run_dns(FakeResend(statuses=["pending", "failed"]), FakeCloudflare(), FakeStore())


def test_rate_limited_cloudflare_is_retried() -> None:
    cloudflare = FakeCloudflare(flaky=1)

    clock = run_dns(FakeResend(), cloudflare, FakeStore())

    assert len(cloudflare.created) == 3
    assert clock.sleeps[0] == 1.0


def test_unknown_zone_is_an_error() -> None:
    with pytest.raises(dns.DnsError, match="zone"):
        run_dns(FakeResend(), FakeCloudflare(), FakeStore(), domain="reels.other.test")


def test_secret_is_only_handed_to_the_store(capsys: pytest.CaptureFixture[str]) -> None:
    store = FakeStore()

    run_dns(FakeResend(), FakeCloudflare(), store)

    assert "sending-token-value" not in capsys.readouterr().out
    assert store.put_calls == [("resend-api-key", "sending-token-value")]
