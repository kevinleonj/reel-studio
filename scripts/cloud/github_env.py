"""`make github-env`: the GitHub `beta` approval gate as code (F417).

GitHub creates a missing environment unprotected the first time a job names it, and the deployer's
Workload Identity binding trusts any job in `beta` (infra/bootstrap/wif.tf). This sets the gate
explicitly: the repository owner as the only required reviewer, self-review allowed (Kevin
dispatches and approves his own deploys), no wait timer, and deployments from `main` only. It then
reads the environment back and fails unless GitHub reports exactly that. Safe to run twice: the PUT
is idempotent and the branch policy is only added when missing. It only adds protection.
"""

import json
import sys

from reel_studio.core.config import GithubEnv, load_cloud
from scripts.cloud._shell import CommandError, Runner, run, say


class GateError(Exception):
    """GitHub reports a gate other than the one requested."""


def owner_id(runner: Runner, repo: str, timeout_s: float) -> int:
    out = runner(["gh", "api", f"repos/{repo}", "--jq", ".owner.id"], None, timeout_s)
    return int(out.strip())


def get_json(runner: Runner, path: str, timeout_s: float) -> dict[str, object]:
    body: dict[str, object] = json.loads(runner(["gh", "api", path], None, timeout_s))
    return body


def write_json(runner: Runner, method: str, path: str, body: object, timeout_s: float) -> None:
    runner(["gh", "api", "-X", method, path, "--input", "-"], json.dumps(body), timeout_s)


def policy_names(runner: Runner, path: str, timeout_s: float) -> list[str]:
    listed = get_json(runner, path, timeout_s).get("branch_policies", [])
    if not isinstance(listed, list):
        raise GateError("branch policies: unexpected response shape")
    return [
        str(p.get("name"))
        for p in listed
        if isinstance(p, dict) and p.get("type", "branch") == "branch"
    ]


def dicts(value: object) -> list[dict[str, object]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def verify(runner: Runner, repo: str, cfg: GithubEnv, owner: int, timeout_s: float) -> None:
    env_path = f"repos/{repo}/environments/{cfg.name}"
    env = get_json(runner, env_path, timeout_s)
    rules = dicts(env.get("protection_rules"))
    reviewers_rule = next((r for r in rules if r.get("type") == "required_reviewers"), None)
    if reviewers_rule is None:
        raise GateError(f"{cfg.name}: no required reviewers")
    ids = []
    for entry in dicts(reviewers_rule.get("reviewers")):
        reviewer = entry.get("reviewer")
        ids.append(reviewer.get("id") if isinstance(reviewer, dict) else None)
    if ids != [owner]:
        raise GateError(f"{cfg.name}: reviewers {ids}, expected only the owner {owner}")
    self_review = reviewers_rule.get("prevent_self_review")
    if self_review is not cfg.prevent_self_review:
        raise GateError(f"{cfg.name}: prevent_self_review is {self_review}")
    policy = env.get("deployment_branch_policy")
    if not isinstance(policy, dict) or policy.get("custom_branch_policies") is not True:
        raise GateError(f"{cfg.name}: deployment branch policy is not custom: {policy}")
    names = policy_names(runner, f"{env_path}/deployment-branch-policies", timeout_s)
    if names != [cfg.branch]:
        raise GateError(f"{cfg.name}: branch policies {names}, expected only {cfg.branch}")


def ensure_environment(runner: Runner, repo: str, cfg: GithubEnv, timeout_s: float) -> None:
    owner = owner_id(runner, repo, timeout_s)
    env_path = f"repos/{repo}/environments/{cfg.name}"
    write_json(
        runner,
        "PUT",
        env_path,
        {
            "wait_timer": cfg.wait_timer_minutes,
            "prevent_self_review": cfg.prevent_self_review,
            "reviewers": [{"type": "User", "id": owner}],
            "deployment_branch_policy": {
                "protected_branches": False,
                "custom_branch_policies": True,
            },
        },
        timeout_s,
    )
    policies_path = f"{env_path}/deployment-branch-policies"
    if cfg.branch not in policy_names(runner, policies_path, timeout_s):
        write_json(runner, "POST", policies_path, {"name": cfg.branch, "type": "branch"}, timeout_s)
    verify(runner, repo, cfg, owner, timeout_s)
    say(f"github-env: {cfg.name} requires the owner's approval and deploys only from {cfg.branch}")


def main() -> int:
    cloud = load_cloud()
    timeout_s = cloud.gcloud.timeout_s
    try:
        repo = run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
            None,
            timeout_s,
        ).strip()
        ensure_environment(run, repo, cloud.github_env, timeout_s)
    except (CommandError, GateError, ValueError) as exc:
        say(f"github-env: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
