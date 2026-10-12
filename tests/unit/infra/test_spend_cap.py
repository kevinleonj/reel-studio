"""scripts/cloud/spend_cap.py (`make spend-cap`, `make spend-cap-lift`) against a recording client.

Never run against Google in this step (the project does not exist yet). The fake Budget API
answers in the documented shapes (FACTS F414): list -> {budgets, nextPageToken}, errors ->
{error: {message}}.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field

import httpx
import pytest

from reel_studio.core import config
from scripts.cloud import _shell, spend_cap

PROJECT, NUMBER, ACCOUNT = "reel-studio-beta-test", "123456789012", "000000-000000-000000"
FAKE_TOKEN = "test-access-token"


def target(units: str | None = None, service: str | None = None) -> spend_cap.Target:
    cfg = config.load_cloud().spend_cap
    return spend_cap.Target(
        billing_account=ACCOUNT,
        project=PROJECT,
        project_number=NUMBER,
        service=service if service is not None else cfg.service,
        currency="EUR",
        units=units if units is not None else str(cfg.amount_units),
    )


@dataclass
class FakeBudgets:
    pages: list[list[dict[str, object]]] = field(default_factory=lambda: [[]])
    refuse: str | None = None
    requests: list[httpx.Request] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.refuse is not None and request.method != "GET":
            return httpx.Response(400, json={"error": {"code": 400, "message": self.refuse}})
        if request.method == "GET":
            token = request.url.params.get("pageToken")
            index = int(token) if token else 0
            body: dict[str, object] = {"budgets": self.pages[index]}
            if index + 1 < len(self.pages):
                body["nextPageToken"] = str(index + 1)
            return httpx.Response(200, json=body)
        return httpx.Response(
            200, json={"name": "billingAccounts/x/budgets/new", **json.loads(request.content)}
        )

    def writes(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method != "GET"]


def api(fake: FakeBudgets) -> spend_cap.BudgetApi:
    client = httpx.Client(base_url="https://budgets.test/v1", transport=httpx.MockTransport(fake))
    return spend_cap.BudgetApi(client, ACCOUNT)


def existing_cap(units: str, state: str = "CONFIGURED") -> dict[str, object]:
    # Copied from the response samples on the Budget API spend-cap page (F414): responses carry
    # spendCap.outputState only (inputState is write-only) and name the project by number.
    return {
        "name": f"billingAccounts/{ACCOUNT}/budgets/cap-1",
        "displayName": "spend cap",
        "budgetFilter": {
            "projects": [f"projects/{NUMBER}"],
            "services": [target().service],
            "creditTypesTreatment": "EXCLUDE_ALL_CREDITS",
            "calendarPeriod": "MONTH",
        },
        "amount": {"specifiedAmount": {"currencyCode": "EUR", "units": units}},
        "thresholdRules": [
            {"thresholdPercent": 0.5, "spendBasis": "CURRENT_SPEND"},
            {"thresholdPercent": 0.8, "spendBasis": "CURRENT_SPEND"},
            {"thresholdPercent": 1, "spendBasis": "CURRENT_SPEND"},
        ],
        "notificationsRule": {"enableProjectLevelRecipients": True},
        "etag": "abc",
        "spendCap": {"outputState": state},
    }


def test_first_run_creates_the_documented_spend_cap() -> None:
    fake = FakeBudgets()

    outcome = spend_cap.ensure_cap(api(fake), target())

    assert outcome == "created"
    [post] = fake.writes()
    assert post.method == "POST"
    assert post.url.path == f"/v1/billingAccounts/{ACCOUNT}/budgets"
    body = json.loads(post.content)
    assert body == {
        "displayName": config.load_cloud().spend_cap.display_name,
        "budgetFilter": {
            "projects": [f"projects/{PROJECT}"],
            "services": [target().service],
            "creditTypesTreatment": "EXCLUDE_ALL_CREDITS",
            "calendarPeriod": "MONTH",
        },
        "amount": {"specifiedAmount": {"currencyCode": "EUR", "units": target().units}},
        "thresholdRules": [
            {"thresholdPercent": 0.5, "spendBasis": "CURRENT_SPEND"},
            {"thresholdPercent": 0.8, "spendBasis": "CURRENT_SPEND"},
            {"thresholdPercent": 1.0, "spendBasis": "CURRENT_SPEND"},
        ],
        "notificationsRule": {"enableProjectLevelRecipients": True},
        "spendCap": {"inputState": "CONFIGURED"},
    }


def test_second_run_sends_no_write(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeBudgets(pages=[[existing_cap(target().units)]])

    assert spend_cap.ensure_cap(api(fake), target()) == "unchanged"

    assert fake.writes() == []
    assert "CONFIGURED" in capsys.readouterr().out


def test_a_different_amount_is_patched_not_recreated() -> None:
    fake = FakeBudgets(pages=[[existing_cap("10")]])

    assert spend_cap.ensure_cap(api(fake), target()) == "updated"

    [patch] = fake.writes()
    assert patch.method == "PATCH"
    assert patch.url.path == f"/v1/billingAccounts/{ACCOUNT}/budgets/cap-1"
    assert patch.url.params["updateMask"] == "amount.specifiedAmount"
    assert json.loads(patch.content) == {
        "amount": {"specifiedAmount": {"currencyCode": "EUR", "units": target().units}}
    }


def test_an_enforced_cap_is_left_alone_with_the_reason() -> None:
    fake = FakeBudgets(pages=[[existing_cap("10", state="ENFORCED")]])

    with pytest.raises(spend_cap.BudgetApiError, match="ENFORCED"):
        spend_cap.ensure_cap(api(fake), target())

    assert fake.writes() == []


def test_the_cap_is_found_on_a_later_page() -> None:
    fake = FakeBudgets(pages=[[], [existing_cap(target().units)]])

    assert spend_cap.ensure_cap(api(fake), target()) == "unchanged"
    assert fake.writes() == []


def test_an_alerts_only_budget_or_another_service_is_not_the_cap() -> None:
    alerts_only = {k: v for k, v in existing_cap(target().units).items() if k != "spendCap"}
    other = existing_cap(target().units)
    other["budgetFilter"] = {"projects": [f"projects/{NUMBER}"], "services": ["services/OTHER"]}
    fake = FakeBudgets(pages=[[alerts_only, other]])

    assert spend_cap.ensure_cap(api(fake), target()) == "created"


def test_another_service_can_be_capped_from_the_arguments() -> None:
    gemini = "services/AEFD-7695-64FA"
    fake = FakeBudgets()

    spend_cap.ensure_cap(api(fake), target(service=gemini))

    [post] = fake.writes()
    assert json.loads(post.content)["budgetFilter"]["services"] == [gemini]


def test_a_refusal_prints_googles_reason_and_the_console_fallback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = FakeBudgets(refuse="Spend caps are not available for this billing account.")

    code = spend_cap.cap_command(api(fake), target())

    out = capsys.readouterr().out
    assert code != 0
    assert "Spend caps are not available for this billing account." in out
    assert "Spend cap enforcement" in out  # the console path from the spend-caps page


def test_lift_needs_the_typed_project_id() -> None:
    fake = FakeBudgets(pages=[[existing_cap(target().units, state="ENFORCED")]])

    assert spend_cap.lift_command(api(fake), target(), confirm=lambda prompt: "yes") != 0
    assert fake.writes() == []


def test_lift_patches_awaiting_next_period() -> None:
    fake = FakeBudgets(pages=[[existing_cap(target().units, state="ENFORCED")]])

    assert spend_cap.lift_command(api(fake), target(), confirm=lambda prompt: PROJECT) == 0

    [patch] = fake.writes()
    assert patch.url.params["updateMask"] == "spendCap.inputState"
    assert json.loads(patch.content) == {"spendCap": {"inputState": "AWAITING_NEXT_PERIOD"}}


def test_lift_without_a_cap_is_an_error() -> None:
    fake = FakeBudgets()

    assert spend_cap.lift_command(api(fake), target(), confirm=lambda prompt: PROJECT) != 0
    assert fake.writes() == []


def test_lift_refuses_a_cap_that_is_not_enforced() -> None:
    fake = FakeBudgets(pages=[[existing_cap(target().units, state="CONFIGURED")]])

    assert spend_cap.lift_command(api(fake), target(), confirm=lambda prompt: PROJECT) != 0
    assert fake.writes() == []


class FakeGcloud:
    def __init__(self, answer: str = FAKE_TOKEN) -> None:
        self.token = answer
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str], stdin: str | None, timeout_s: float) -> str:
        self.calls.append(list(args))
        if args[1:3] == ["projects", "describe"]:
            return f"{NUMBER}\n"
        if args[1:3] == ["auth", "print-access-token"]:
            return f"{self.token}\n"
        if args[1:4] == ["billing", "accounts", "describe"]:
            return json.dumps({"currencyCode": "EUR"})
        raise AssertionError(f"unexpected command {args}")


def test_build_sets_auth_quota_project_currency_and_amount() -> None:
    gcloud = FakeGcloud()

    budgets, built = spend_cap.build(gcloud, ACCOUNT, PROJECT, target().service, 5.0)

    client = budgets._client  # the one place the headers can be seen
    assert client.headers["Authorization"] == f"Bearer {FAKE_TOKEN}"
    assert client.headers["x-goog-user-project"] == PROJECT
    assert built == target()
    assert all(FAKE_TOKEN not in " ".join(c) for c in gcloud.calls)


@pytest.mark.parametrize(
    "token", ["", "two words", "line\nbreak"], ids=["empty", "space", "newline"]
)
def test_an_unusable_token_never_reaches_a_header(token: str) -> None:
    with pytest.raises(_shell.CommandError, match="no usable token"):
        spend_cap.build(FakeGcloud(answer=token), ACCOUNT, PROJECT, target().service, 5.0)


def test_transport_errors_print_the_type_not_the_text(capsys: pytest.CaptureFixture[str]) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.LocalProtocolError("Illegal header value b'Bearer secret-token'")

    client = httpx.Client(base_url="https://budgets.test/v1", transport=httpx.MockTransport(fail))

    code = spend_cap.cap_command(spend_cap.BudgetApi(client, ACCOUNT), target())

    out = capsys.readouterr().out
    assert code != 0
    assert "LocalProtocolError" in out
    assert "secret-token" not in out


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json=["a"]),
        httpx.Response(200, json={"budgets": "x"}),
    ],
    ids=["not-json", "list", "budgets-not-list"],
)
def test_an_unexpected_answer_takes_the_refusal_path(
    answer: httpx.Response, capsys: pytest.CaptureFixture[str]
) -> None:
    client = httpx.Client(
        base_url="https://budgets.test/v1", transport=httpx.MockTransport(lambda r: answer)
    )

    assert spend_cap.cap_command(spend_cap.BudgetApi(client, ACCOUNT), target()) != 0
    assert "Console fallback" in capsys.readouterr().out
