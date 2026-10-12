"""scripts/cloud/github_env.py (`make github-env`): the beta approval gate as code (F417).

A stateful fake answers `gh api` like GitHub's environments and branch-policy endpoints.
"""

import json
from collections.abc import Sequence

import pytest

from reel_studio.core import config
from scripts.cloud import _shell, github_env

REPO = "owner/repo"
OWNER_ID = 4242
TIMEOUT_S = 9.0


class FakeGitHub:
    def __init__(self, *, policies: list[str] | None = None, drift: bool = False) -> None:
        self.environment: dict[str, object] | None = None
        self.policies = [
            {"id": i, "name": n, "type": "branch"} for i, n in enumerate(policies or [])
        ]
        self.drift = drift  # GitHub answers with a setting other than the one sent
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(self, args: Sequence[str], stdin: str | None, timeout_s: float) -> str:
        argv = list(args)
        self.calls.append((argv, stdin))
        method = argv[argv.index("-X") + 1] if "-X" in argv else "GET"
        path = next(a for a in argv[2:] if a.startswith("repos/"))
        if path == f"repos/{REPO}":
            return f"{OWNER_ID}\n"
        if path.endswith("/deployment-branch-policies"):
            if method == "POST":
                body = json.loads(stdin or "{}")
                self.policies.append({"id": len(self.policies), **body})
                return json.dumps(self.policies[-1])
            return json.dumps({"total_count": len(self.policies), "branch_policies": self.policies})
        if method == "PUT":
            body = json.loads(stdin or "{}")
            self.environment = body
            return json.dumps({"name": "beta"})
        return json.dumps(self.rendered())

    def rendered(self) -> dict[str, object]:
        body = self.environment if self.environment is not None else {}
        sent = body.get("reviewers", [])
        reviewers = [
            {"type": r["type"], "reviewer": {"id": r["id"], "login": "owner"}}
            for r in (sent if isinstance(sent, list) else [])
        ]
        rule = {
            "type": "required_reviewers",
            "prevent_self_review": self.drift,
            "reviewers": reviewers,
        }
        return {
            "name": "beta",
            "protection_rules": [rule],
            "deployment_branch_policy": body.get("deployment_branch_policy"),
        }

    def writes(self) -> list[tuple[list[str], str | None]]:
        return [c for c in self.calls if "-X" in c[0]]


def cfg() -> config.GithubEnv:
    return config.load_cloud().github_env


def test_first_run_creates_the_gate_and_the_main_policy() -> None:
    github = FakeGitHub()

    github_env.ensure_environment(github, REPO, cfg(), TIMEOUT_S)

    put, post = github.writes()
    assert put[0][:5] == ["gh", "api", "-X", "PUT", f"repos/{REPO}/environments/{cfg().name}"]
    assert json.loads(put[1] or "") == {
        "wait_timer": 0,
        "prevent_self_review": False,
        "reviewers": [{"type": "User", "id": OWNER_ID}],
        "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True},
    }
    assert post[0][:4] == ["gh", "api", "-X", "POST"]
    assert json.loads(post[1] or "") == {"name": cfg().branch, "type": "branch"}


def test_second_run_does_not_add_the_branch_policy_twice() -> None:
    github = FakeGitHub(policies=[cfg().branch])

    github_env.ensure_environment(github, REPO, cfg(), TIMEOUT_S)

    assert [c[0][3] for c in github.writes()] == ["PUT"]


def test_the_reviewer_is_the_repository_owner_read_from_github() -> None:
    github = FakeGitHub()

    github_env.ensure_environment(github, REPO, cfg(), TIMEOUT_S)

    first = github.calls[0][0]
    assert first == ["gh", "api", f"repos/{REPO}", "--jq", ".owner.id"]


def test_a_gate_that_reads_back_differently_fails() -> None:
    with pytest.raises(github_env.GateError, match="prevent_self_review"):
        github_env.ensure_environment(FakeGitHub(drift=True), REPO, cfg(), TIMEOUT_S)


def test_an_extra_branch_policy_fails_the_check() -> None:
    github = FakeGitHub(policies=[cfg().branch, "release"])

    with pytest.raises(github_env.GateError, match="branch policies"):
        github_env.ensure_environment(github, REPO, cfg(), TIMEOUT_S)


def test_a_gh_failure_is_a_command_error() -> None:
    def refuse(args: Sequence[str], stdin: str | None, timeout_s: float) -> str:
        raise _shell.CommandError("gh api exited 1: HTTP 403")

    with pytest.raises(_shell.CommandError, match="403"):
        github_env.ensure_environment(refuse, REPO, cfg(), TIMEOUT_S)


class DriftingGitHub(FakeGitHub):
    """Answers GET with one field changed from what was sent."""

    def __init__(self, change: str) -> None:
        super().__init__(policies=[cfg().branch])
        self.change = change

    def rendered(self) -> dict[str, object]:
        env = super().rendered()
        rules = env["protection_rules"]
        assert isinstance(rules, list)
        rule = rules[0]
        if self.change == "other reviewer":
            rule["reviewers"] = [{"type": "User", "reviewer": {"id": OWNER_ID + 1}}]
        elif self.change == "second reviewer":
            rule["reviewers"] = [*rule["reviewers"], {"type": "User", "reviewer": {"id": 7}}]
        elif self.change == "team with the owner's id":
            rule["reviewers"] = [{"type": "Team", "reviewer": {"id": OWNER_ID}}]
        elif self.change == "no reviewers rule":
            env["protection_rules"] = []
        elif self.change == "protected branches":
            env["deployment_branch_policy"] = {
                "protected_branches": True,
                "custom_branch_policies": False,
            }
        return env


@pytest.mark.parametrize(
    "change",
    [
        "other reviewer",
        "second reviewer",
        "team with the owner's id",
        "no reviewers rule",
        "protected branches",
    ],
)
def test_every_read_back_assertion_catches_its_drift(change: str) -> None:
    with pytest.raises(github_env.GateError):
        github_env.ensure_environment(DriftingGitHub(change), REPO, cfg(), TIMEOUT_S)


def test_a_tag_policy_beside_main_fails_the_check() -> None:
    github = FakeGitHub(policies=[cfg().branch])
    github.policies.append({"id": 9, "name": "*", "type": "tag"})

    with pytest.raises(github_env.GateError, match="branch policies"):
        github_env.ensure_environment(github, REPO, cfg(), TIMEOUT_S)
