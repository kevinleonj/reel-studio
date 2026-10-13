"""`reel job` (MAIN-NEXT task 3): one reel-editor execution, end to end against the fakes. The
cloud adapters run over the fake bucket, Resend and Cloud Run clients; the engine is replaced,
so no model is called."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from reel_studio.adapters.launcher_real import MadeReel
from reel_studio.api.cloud import Budget, CloudClients, cloud_adapters
from reel_studio.cli import job
from reel_studio.core.config import load, load_cloud
from reel_studio.core.ports import NewOrder
from reel_studio.settings import JobSettings, RuntimeSettings
from tests.conftest import MakeSettings
from tests.fakes.clock import FrozenClock
from tests.fakes.gcp import FakeBucket, FakeJobsClient
from tests.fakes.orders import FakeOrders
from tests.unit.api.conftest import LIMITS, START
from tests.unit.api.test_cloud_composition import CLOUD, RESEND, Sent

SETTINGS = {"style": "recipe", "length_s": 30, "text_lang": "en", "keep_voice": False}
A, B, X = f"{10:032x}", f"{11:032x}", f"{12:032x}"
EMAIL = "friend@example.test"


class World:
    """One project's fakes: orders, bucket, Resend and the Cloud Run jobs client."""

    def __init__(self, make_settings: MakeSettings) -> None:
        self.clock = FrozenClock(START)
        self.orders = FakeOrders(self.clock, LIMITS)
        self.bucket, self.jobs, self.sent = FakeBucket(), FakeJobsClient(), Sent()
        runtime = make_settings(RuntimeSettings, **CLOUD)
        assert isinstance(runtime, RuntimeSettings)
        clients = CloudClients(
            bucket=self.bucket,
            identity=lambda: pytest.fail("the job signs nothing"),
            jobs=self.jobs,
            resend=httpx.Client(base_url=RESEND, transport=httpx.MockTransport(self.sent)),
            sessions=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(499))),
        )
        cloud = load_cloud()
        adapters = cloud_adapters(runtime, cloud, clients, self.orders, Budget.job(cloud))
        self.ports = job.JobPorts.of(adapters, self.orders, runtime, load())

    def order(self, order_id: str, *, files: tuple[str, ...] = ("a.mp4",)) -> None:
        self.orders.create_awaiting_payment(
            NewOrder(order_id, f"h-{order_id}", SETTINGS, EMAIL, START)
        )
        self.orders.mark_paid(order_id, {"email": EMAIL})
        for name in files:
            self.bucket.contents[f"in/{order_id}/{name}"] = name.encode()
        manifest = [{"name": n, "size": len(n)} for n in files]
        self.orders.set_manifest(order_id, files=manifest, bytes_declared=len(files))
        self.orders.queue(order_id)

    def token(self, order_id: str) -> str:
        assert self.orders.take_slot(order_id)
        doc = self.orders.get(order_id)
        assert doc is not None and isinstance(doc["queue"], dict)
        return str(doc["queue"]["run_token"])


class Engine:
    """Stands in for the engine's `make`: records each call, writes two small Reels."""

    def __init__(self, fails: Exception | None = None) -> None:
        self.inputs: list[list[str]] = []
        self.fails = fails

    def __call__(self, inputs: Path, out: Path, settings: dict[str, object]) -> MadeReel:
        self.inputs.append(sorted(p.name for p in inputs.iterdir()))
        if self.fails is not None:
            raise self.fails
        out.mkdir(parents=True, exist_ok=True)
        (out / "text.mp4").write_bytes(b"with text")
        (out / "clean.mp4").write_bytes(b"clean")
        return MadeReel(
            out / "text.mp4",
            out / "clean.mp4",
            Decimal("0.91"),
            30,
            "Tomato toast\n#food",
            [],
            None,
        )


def settings(order_id: str, token: str) -> JobSettings:
    return JobSettings(_env_file=None, order_id=order_id, run_token=SecretStr(token))


def launched(jobs: FakeJobsClient) -> list[str]:
    """The ORDER_ID of every execution started, in order."""
    found = []
    for call in jobs.calls:
        request: Any = call["request"]
        [override] = request.overrides.container_overrides
        found.append({e.name: e.value for e in override.env}["ORDER_ID"])
    return found


def test_one_order_is_edited_saved_mailed_and_the_next_one_started(
    make_settings: MakeSettings,
) -> None:
    world, engine = World(make_settings), Engine()
    world.order(A)
    world.order(X)
    token = world.token(A)
    world.token(X)  # both slots taken
    world.order(B)  # waits for a slot

    assert job.run_job(settings(A, token), world.ports, engine) == job.OK

    doc = world.orders.get(A)
    assert doc is not None and doc["status"] == "done"
    assert doc["cost"] == {"usd_total": "0.91"}
    assert world.bucket.contents[f"out/{A}/text.mp4"] == b"with text"
    assert world.bucket.contents[f"out/{A}/clean.mp4"] == b"clean"
    assert engine.inputs == [["a.mp4"]]
    [ready] = world.sent.bodies
    assert ready["to"] == [EMAIL]
    assert "Tomato toast" in str(ready["subject"])
    assert f"/o/{A}" not in json.dumps(ready)  # no link without its token (D18)
    assert launched(world.jobs) == [B]
    started = world.orders.get(B)
    assert started is not None and started["status"] == "running"


def test_a_second_execution_with_the_same_token_does_nothing(make_settings: MakeSettings) -> None:
    world, engine = World(make_settings), Engine()
    world.order(A)
    token = world.token(A)

    assert job.run_job(settings(A, token), world.ports, engine) == job.OK
    assert job.run_job(settings(A, token), world.ports, engine) == job.OK

    assert len(engine.inputs) == 1
    assert len(world.sent.bodies) == 1


def test_a_wrong_token_edits_nothing(make_settings: MakeSettings) -> None:
    world, engine = World(make_settings), Engine()
    world.order(A)
    world.token(A)

    assert job.run_job(settings(A, "not-the-token"), world.ports, engine) == job.OK

    assert engine.inputs == []
    doc = world.orders.get(A)
    assert doc is not None and doc["status"] == "running"


def test_only_the_files_in_the_manifest_are_edited(make_settings: MakeSettings) -> None:
    """A resumable session that finished after Start lands in the bucket too (web.md, For
    CLOUD): the editor reads what Start listed, nothing else."""
    world, engine = World(make_settings), Engine()
    world.order(A, files=("a.mp4", "b.mov"))
    world.bucket.contents[f"in/{A}/late.mp4"] = b"late"
    token = world.token(A)

    job.run_job(settings(A, token), world.ports, engine)

    assert engine.inputs == [["a.mp4", "b.mov"]]


def test_an_engine_crash_fails_the_order_tells_kevin_and_still_starts_the_next(
    make_settings: MakeSettings,
) -> None:
    world, engine = World(make_settings), Engine(fails=RuntimeError("ffmpeg vanished"))
    world.order(A)
    world.order(X)
    token = world.token(A)
    world.token(X)
    world.order(B)

    assert job.run_job(settings(A, token), world.ports, engine) == job.FAILED

    doc = world.orders.get(A)
    assert doc is not None and doc["status"] == "failed"
    assert isinstance(doc["error"], dict) and doc["error"]["code"] == "render_error"
    assert len(world.sent.bodies) == 2  # Kevin's alert and the customer's failure email
    assert launched(world.jobs) == [B]


def test_settings_problems_name_the_variable_never_its_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUN_TOKEN", "planted-token-value")
    with pytest.raises(SystemExit) as stopped:
        job.main()
    assert "ORDER_ID" in str(stopped.value)
    assert "planted-token-value" not in str(stopped.value)


def test_reel_job_runs_the_job(monkeypatch: pytest.MonkeyPatch) -> None:
    from reel_studio.cli import reel  # noqa: PLC0415

    monkeypatch.setattr(job, "main", lambda: 7)
    assert reel.main(["job"]) == 7
