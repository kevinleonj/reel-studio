"""`make bootstrap-plan`: plan infra/bootstrap and print the apply command for Kevin.

Claude Code is denied `terraform apply` (docs/INFRA.md §1); this script only plans. It reads the
budget currency from the billing account (currencyCode, fixed at account creation) and the
numeric repository ids the Workload Identity condition needs from GitHub.
"""

import json
import sys

from reel_studio.core.config import load_cloud
from reel_studio.settings import CloudSettings
from scripts.cloud._shell import CommandError, Runner, run, say

ROOT = "infra/bootstrap"
PLAN_FILE = "tfplan"  # ignored by infra/.gitignore


def billing_currency(runner: Runner, billing_account: str, timeout_s: float) -> str:
    out = runner(
        ["gcloud", "billing", "accounts", "describe", billing_account, "--format=json"],
        None,
        timeout_s,
    )
    currency = json.loads(out).get("currencyCode")
    if not isinstance(currency, str) or not currency:
        raise CommandError("billing account has no currencyCode")
    return currency


def repository_ids(runner: Runner, repository: str, timeout_s: float) -> tuple[str, str]:
    out = runner(["gh", "api", f"repos/{repository}", "--jq", ".id,.owner.id"], None, timeout_s)
    lines = out.split()
    if len(lines) != len(("id", "owner")):
        raise CommandError(f"gh api repos/{repository} returned {len(lines)} values, expected 2")
    return lines[0], lines[1]


def plan(
    runner: Runner, project: str, billing_account: str, repository: str, timeout_s: float
) -> None:
    currency = billing_currency(runner, billing_account, timeout_s)
    repo_id, owner_id = repository_ids(runner, repository, timeout_s)
    runner(["terraform", f"-chdir={ROOT}", "init", "-input=false"], None, timeout_s)
    runner(
        [
            "terraform",
            f"-chdir={ROOT}",
            "plan",
            "-input=false",
            f"-out={PLAN_FILE}",
            f"-var=project_id={project}",
            f"-var=billing_account={billing_account}",
            f"-var=budget_currency_code={currency}",
            f"-var=github_repository_id={repo_id}",
            f"-var=github_repository_owner_id={owner_id}",
        ],
        None,
        timeout_s,
    )
    say(f"bootstrap-plan: plan saved to {ROOT}/{PLAN_FILE}. Review it, then run yourself:")
    say(f"  terraform -chdir={ROOT} apply {PLAN_FILE}")


def main() -> int:
    settings = CloudSettings()
    timeout_s = load_cloud().gcloud.timeout_s
    try:
        repository = run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
            None,
            timeout_s,
        ).strip()
        plan(run, settings.gcp_project, settings.gcp_billing_account, repository, timeout_s)
    except CommandError as exc:
        say(f"bootstrap-plan: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
