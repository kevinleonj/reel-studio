"""scripts/cloud/spend_cap.py (`make spend-cap`, `make spend-cap-lift`) against a recording client.

Never run against Google in this step (the project does not exist yet). The fake Budget API
answers in the documented shapes (FACTS F414): list -> {budgets, nextPageToken}, errors ->
{error: {message}}.
"""

import json
from dataclasses import dataclass, field

import httpx
import pytest

from reel_studio.core import config
from scripts.cloud import spend_cap

PROJECT, NUMBER, ACCOUNT = "reel-studio-beta-test", "123456789012", "000000-000000-000000"


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
    # The API reports projects by number (UNCONFIRMED: matched by id or number either way).
    return {
        "name": f"billingAccounts/{ACCOUNT}/budgets/cap-1",
        "budgetFilter": {"projects": [f"projects/{NUMBER}"], "services": [target().service]},
        "amount": {"specifiedAmount": {"currencyCode": "EUR", "units": units}},
        "spendCap": {"inputState": "CONFIGURED", "outputState": state},
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
