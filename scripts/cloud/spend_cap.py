"""`make spend-cap` / `make spend-cap-lift`: a hard stop on one service's monthly bill (F414).

A budget with spend-cap enforcement for exactly one project and one eligible service (Cloud Run by
default; `--service` caps another, e.g. the Gemini API on the project that owns that key). When the
gross estimated cost passes the amount, Google pauses new usage of that service in that project
until the next month or a lift; nothing is deleted, and enforcement lags reporting, so some
overage is still billed. Terraform cannot express this (google_billing_budget has no spend-cap
argument), so this script calls the Budget API with Kevin's gcloud login, like make stripe-setup.

Safe to run twice: an existing cap for the same project and service is kept, and only its amount is
patched when it differs. While a cap is ENFORCED only `make spend-cap-lift` can change it.
"""

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from reel_studio.core.config import load_cloud
from reel_studio.settings import CloudSettings
from scripts.cloud._shell import CommandError, Runner, run, say
from scripts.cloud.bootstrap_plan import billing_currency

BUDGETS_API = "https://billingbudgets.googleapis.com/v1"  # hardcode-ok: vendor base URL (F414)
# The spend-cap rules the API accepts, verbatim (F414): fixed thresholds on current spend, gross
# cost, monthly, project-level recipients only. Not tunables.
THRESHOLDS = (0.5, 0.8, 1.0)
CURRENT_SPEND = "CURRENT_SPEND"
CONFIGURED, ENFORCED, LIFTED = "CONFIGURED", "ENFORCED", "AWAITING_NEXT_PERIOD"
# Console path from the spend-caps page (F414), printed when the API refuses.
CONSOLE_FALLBACK = (
    "Console fallback: Billing > Budgets & alerts > Create new budget > Spend cap enforcement;"
    " scope one project and one eligible service; enter the amount; Finish."
)

Body = dict[str, object]


class BudgetApiError(Exception):
    """The Budget API refused, or the cap is in a state this run must not change."""


@dataclass(frozen=True)
class Target:
    billing_account: str
    project: str
    project_number: str
    service: str
    currency: str
    units: str


class BudgetApi:
    """The Budget API calls used here; the client carries the base URL, auth and quota project."""

    def __init__(self, client: httpx.Client, billing_account: str) -> None:
        self._client = client
        self._parent = f"/billingAccounts/{billing_account}/budgets"

    def _call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: Body | None = None,
    ) -> Body:
        response = self._client.request(method, path, params=params, json=body)
        if not response.is_success:
            try:
                reason = str(response.json().get("error", {}).get("message", ""))
            except ValueError:
                reason = response.text[:200]
            raise BudgetApiError(f"{method} budgets: HTTP {response.status_code}: {reason}")
        body: Body = response.json()
        return body

    def list_budgets(self) -> list[Body]:
        budgets: list[Body] = []
        token = ""
        while True:
            page = self._call("GET", self._parent, params={"pageToken": token} if token else {})
            found = page.get("budgets", [])
            budgets += [b for b in found if isinstance(b, dict)] if isinstance(found, list) else []
            token = str(page.get("nextPageToken") or "")
            if not token:
                return budgets

    def create(self, body: Body) -> Body:
        return self._call("POST", self._parent, body=body)

    def patch(self, name: str, mask: str, body: Body) -> Body:
        budget_id = name.rsplit("/", 1)[-1]
        return self._call(
            "PATCH", f"{self._parent}/{budget_id}", params={"updateMask": mask}, body=body
        )


def amount(target: Target) -> Body:
    return {"specifiedAmount": {"currencyCode": target.currency, "units": target.units}}


def cap_body(target: Target, display_name: str) -> Body:
    return {
        "displayName": display_name,
        "budgetFilter": {
            "projects": [f"projects/{target.project}"],
            "services": [target.service],
            "creditTypesTreatment": "EXCLUDE_ALL_CREDITS",
            "calendarPeriod": "MONTH",
        },
        "amount": amount(target),
        "thresholdRules": [
            {"thresholdPercent": t, "spendBasis": CURRENT_SPEND} for t in THRESHOLDS
        ],
        "notificationsRule": {"enableProjectLevelRecipients": True},
        "spendCap": {"inputState": CONFIGURED},
    }


def find_cap(budgets: list[Body], target: Target) -> Body | None:
    """The spend-cap budget for this project (by id or number) and service, if any."""
    projects = {f"projects/{target.project}", f"projects/{target.project_number}"}
    for budget in budgets:
        scope = budget.get("budgetFilter")
        cap = budget.get("spendCap")
        if not isinstance(scope, dict) or not isinstance(cap, dict) or not cap.get("inputState"):
            continue  # alerts-only budgets cannot be converted (F414)
        if set(scope.get("projects", [])) & projects and target.service in scope.get(
            "services", []
        ):
            return budget
    return None


def state(budget: Body) -> str:
    cap = budget.get("spendCap")
    if not isinstance(cap, dict):
        return "?"
    return str(cap.get("outputState") or cap.get("inputState") or "?")


def current_units(budget: Body) -> str:
    specified = budget.get("amount", {})
    if isinstance(specified, dict):
        specified = specified.get("specifiedAmount", {})
    return str(specified.get("units", "")) if isinstance(specified, dict) else ""


def ensure_cap(api: BudgetApi, target: Target) -> str:
    """'created', 'updated' or 'unchanged'; raises BudgetApiError on refusal or ENFORCED."""
    found = find_cap(api.list_budgets(), target)
    if found is None:
        api.create(cap_body(target, load_cloud().spend_cap.display_name))
        say(f"spend-cap: created for {target.project} {target.service}")
        say(f"spend-cap: amount {target.units} {target.currency}, state {CONFIGURED}")
        return "created"
    current = state(found)
    if current_units(found) == target.units:
        say(f"spend-cap: exists, {target.units} {target.currency}, state {current}")
        return "unchanged"
    if current == ENFORCED:
        raise BudgetApiError("cap is ENFORCED; only make spend-cap-lift may change it this month")
    api.patch(str(found["name"]), "amount.specifiedAmount", {"amount": amount(target)})
    say(f"spend-cap: amount changed to {target.units} {target.currency}, state {current}")
    return "updated"


def cap_command(api: BudgetApi, target: Target) -> int:
    try:
        ensure_cap(api, target)
    except (BudgetApiError, httpx.HTTPError) as exc:
        say(f"spend-cap: {exc}")
        say(CONSOLE_FALLBACK)
        return 1
    return 0


def lift_command(api: BudgetApi, target: Target, confirm: Callable[[str], str]) -> int:
    """Lift an enforced cap for the rest of the month after the project id is typed back."""
    try:
        found = find_cap(api.list_budgets(), target)
        if found is None:
            say(f"spend-cap-lift: no spend cap for {target.project} {target.service}")
            return 1
        typed = confirm(
            f"Type {target.project} to lift the {target.service} cap until next month: "
        )
        if typed.strip() != target.project:
            say("spend-cap-lift: not confirmed, nothing changed")
            return 1
        api.patch(str(found["name"]), "spendCap.inputState", {"spendCap": {"inputState": LIFTED}})
    except (BudgetApiError, httpx.HTTPError) as exc:
        say(f"spend-cap-lift: {exc}")
        say(CONSOLE_FALLBACK)
        return 1
    say("spend-cap-lift: lifted until the next budget period (services return within an hour)")
    return 0


def build(runner: Runner, project: str, service: str, timeout_s: float) -> tuple[BudgetApi, Target]:
    settings = CloudSettings()
    account = settings.gcp_billing_account
    number = runner(
        ["gcloud", "projects", "describe", project, "--format=value(projectNumber)"],
        None,
        timeout_s,
    ).strip()
    token = runner(["gcloud", "auth", "print-access-token"], None, timeout_s).strip()
    client = httpx.Client(
        base_url=BUDGETS_API,
        timeout=load_cloud().spend_cap.http_timeout_s,
        headers={"Authorization": f"Bearer {token}", "x-goog-user-project": project},
    )
    target = Target(
        billing_account=account,
        project=project,
        project_number=number,
        service=service,
        currency=billing_currency(runner, account, timeout_s),
        units=str(load_cloud().spend_cap.amount_units),
    )
    return BudgetApi(client, account), target


def main(argv: list[str] | None = None) -> int:
    cfg = load_cloud()
    parser = argparse.ArgumentParser(description="Spend cap on one service of one project.")
    parser.add_argument("--project", help="project id (default: GCP_PROJECT from .env)")
    parser.add_argument("--service", default=cfg.spend_cap.service, help="services/XXXX-XXXX-XXXX")
    parser.add_argument("--lift", action="store_true", help="lift an enforced cap until next month")
    options = parser.parse_args(argv)
    project = options.project if options.project is not None else CloudSettings().gcp_project
    try:
        api, target = build(run, project, options.service, cfg.gcloud.timeout_s)
    except CommandError as exc:
        say(f"spend-cap: {exc}")
        return 1
    if options.lift:
        return lift_command(api, target, input)
    return cap_command(api, target)


if __name__ == "__main__":
    sys.exit(main())
