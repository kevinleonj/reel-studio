"""scripts/cloud: gcloud-driven setup (`make gcp-project`, `make secrets-push`, `make
bootstrap-plan`). Written, not run against a project in STEP-08 phase A; a fake runner records
every command, and a secret must only ever travel on stdin."""

import json
import sys
from collections.abc import Sequence

import pytest
from pydantic import SecretStr

from scripts.cloud import _shell, bootstrap_plan, gcp_project, secrets_push

PROJECT = "reel-studio-beta-test"
TIMEOUT_S = 9.0


class FakeRunner:
    def __init__(self, answers: dict[str, str] | None = None, fail: str | None = None) -> None:
        self.answers = answers if answers is not None else {}
        self.fail = fail
        self.calls: list[tuple[list[str], str | None, float]] = []

    def __call__(self, args: Sequence[str], stdin: str | None, timeout_s: float) -> str:
        self.calls.append((list(args), stdin, timeout_s))
        joined = " ".join(args)
        if self.fail is not None and self.fail in joined:
            raise _shell.CommandError(f"{args[0]} failed")
        for needle, answer in self.answers.items():
            if needle in joined:
                return answer
        return ""


# ---------------------------------------------------------------- secrets-push


NEW = "projects/p/secrets/x/versions/7"
OLD = "projects/p/secrets/x/versions/6"


def rotating_runner(state: str = "ENABLED", listed: str = f"{NEW}\n{OLD}\n") -> FakeRunner:
    return FakeRunner(
        answers={
            "versions add": f"{NEW}\n",
            "versions describe": f"{state}\n",
            "versions list": listed,
        }
    )


def commands(runner: FakeRunner, verb: str) -> list[list[str]]:
    return [c[0] for c in runner.calls if c[0][2:4] == ["versions", verb]]


def test_secrets_push_sends_each_value_on_stdin_only() -> None:
    runner = rotating_runner()
    values = {
        "anthropic-api-key": SecretStr("sk-ant-test-1"),
        "gemini-api-key": SecretStr("gem-test-2"),
        "stripe-secret-key": SecretStr("sk_test_3"),
    }

    secrets_push.push_all(runner, PROJECT, values, TIMEOUT_S)

    adds = [c for c in runner.calls if c[0][2:4] == ["versions", "add"]]
    assert [c[1] for c in adds] == ["sk-ant-test-1", "gem-test-2", "sk_test_3"]
    for args, stdin, timeout in runner.calls:
        assert f"--project={PROJECT}" in args
        assert timeout == TIMEOUT_S
        argv = " ".join(args)
        assert not any(v.get_secret_value() in argv for v in values.values()), args
        if stdin is not None:
            assert args[2:4] == ["versions", "add"]
            assert "--data-file=-" in args


def test_secrets_push_destroys_the_previous_version_after_the_new_one_is_enabled() -> None:
    runner = rotating_runner()

    secrets_push.push_all(runner, PROJECT, {"gemini-api-key": SecretStr("g2")}, TIMEOUT_S)

    verbs = [c[0][3] for c in runner.calls]
    assert verbs == ["add", "describe", "list", "destroy"]
    [destroy] = commands(runner, "destroy")
    assert destroy[4:6] == ["6", "--secret=gemini-api-key"]
    assert "--quiet" in destroy
    [listing] = commands(runner, "list")
    assert "--filter=NOT state:DESTROYED" in listing


def test_secrets_push_keeps_old_versions_when_the_new_one_is_not_enabled() -> None:
    runner = rotating_runner(state="DISABLED")

    with pytest.raises(_shell.CommandError, match="older versions kept"):
        secrets_push.push_all(runner, PROJECT, {"gemini-api-key": SecretStr("g2")}, TIMEOUT_S)

    assert commands(runner, "destroy") == []


def test_secrets_push_first_version_destroys_nothing() -> None:
    runner = rotating_runner(listed=f"{NEW}\n")

    secrets_push.push_all(runner, PROJECT, {"gemini-api-key": SecretStr("g2")}, TIMEOUT_S)

    assert commands(runner, "destroy") == []


def test_secrets_push_never_destroys_a_newer_version_from_another_writer() -> None:
    newer = "projects/p/secrets/x/versions/8"
    runner = rotating_runner(listed=f"{newer}\n{NEW}\n{OLD}\n")

    secrets_push.push_all(runner, PROJECT, {"gemini-api-key": SecretStr("g2")}, TIMEOUT_S)

    assert [c[4] for c in commands(runner, "destroy")] == ["6"]


def test_a_failed_rotation_message_never_echoes_the_value() -> None:
    runner = rotating_runner(state="DISABLED")

    with pytest.raises(_shell.CommandError) as caught:
        secrets_push.push_all(
            runner, PROJECT, {"gemini-api-key": SecretStr("g2-secret")}, TIMEOUT_S
        )

    assert "g2-secret" not in str(caught.value)


def test_secrets_push_never_destroys_the_new_version_even_if_listed_twice() -> None:
    runner = rotating_runner(listed=f"{NEW}\n{NEW}\n{OLD}\n")

    secrets_push.push_all(runner, PROJECT, {"gemini-api-key": SecretStr("g2")}, TIMEOUT_S)

    assert [c[4] for c in commands(runner, "destroy")] == ["6"]


def test_secrets_push_names_exactly_the_three_cloud_secrets() -> None:
    # docs/ARCHITECTURE.md §6: the Resend key and the webhook secret are written by make dns
    # and make stripe-setup, never copied from the laptop.
    assert sorted(secrets_push.SECRET_FIELDS.values()) == [
        "anthropic-api-key",
        "gemini-api-key",
        "stripe-secret-key",
    ]


def test_secrets_push_stops_on_the_first_failure_without_echoing_values() -> None:
    runner = FakeRunner(
        answers={
            "versions add": "projects/p/secrets/x/versions/7\n",
            "versions describe": "ENABLED\n",
        },
        fail="gemini-api-key",
    )
    values = {"anthropic-api-key": SecretStr("a1"), "gemini-api-key": SecretStr("g2")}

    with pytest.raises(_shell.CommandError) as caught:
        secrets_push.push_all(runner, PROJECT, values, TIMEOUT_S)

    assert "g2" not in str(caught.value)


def test_empty_secret_is_refused() -> None:
    with pytest.raises(ValueError, match="empty"):
        secrets_push.push_all(FakeRunner(), PROJECT, {"gemini-api-key": SecretStr("")}, TIMEOUT_S)


# ---------------------------------------------------------------- gcp-project


def test_gcp_project_creates_links_and_enables_when_new() -> None:
    runner = FakeRunner(fail="projects describe")

    gcp_project.ensure_project(
        runner, PROJECT, "000000-000000-000000", ["a.googleapis.com"], TIMEOUT_S
    )

    commands = [" ".join(c[0][:4]) for c in runner.calls]
    assert commands == [
        f"gcloud projects describe {PROJECT}",
        f"gcloud projects create {PROJECT}",
        "gcloud billing projects link",
        "gcloud services enable a.googleapis.com",
    ]
    assert "--billing-account=000000-000000-000000" in runner.calls[2][0]


def test_gcp_project_is_safe_to_run_twice() -> None:
    runner = FakeRunner(answers={"projects describe": json.dumps({"projectId": PROJECT})})

    gcp_project.ensure_project(
        runner, PROJECT, "000000-000000-000000", ["a.googleapis.com"], TIMEOUT_S
    )

    assert all(c[0][1:3] != ["projects", "create"] for c in runner.calls)


# ---------------------------------------------------------------- bootstrap-plan


def test_bootstrap_plan_reads_currency_and_ids_then_prints_the_apply_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = FakeRunner(
        answers={
            "billing accounts describe": json.dumps({"currencyCode": "EUR"}),
            "gh api": "123\n456\n",
        }
    )

    bootstrap_plan.plan(runner, PROJECT, "000000-000000-000000", "owner/repo", TIMEOUT_S)

    terraform = [c[0] for c in runner.calls if c[0][0] == "terraform"]
    assert terraform[0][:2] == ["terraform", "-chdir=infra/bootstrap"]
    plan_args = terraform[-1]
    assert "plan" in plan_args
    assert f"-var=project_id={PROJECT}" in plan_args
    assert "-var=budget_currency_code=EUR" in plan_args
    assert "-var=github_repository_id=123" in plan_args
    assert "-var=github_repository_owner_id=456" in plan_args
    assert "-out=tfplan" in plan_args
    out = capsys.readouterr().out
    assert "terraform -chdir=infra/bootstrap apply tfplan" in out


def test_bootstrap_plan_never_applies() -> None:
    runner = FakeRunner(
        answers={
            "billing accounts describe": json.dumps({"currencyCode": "EUR"}),
            "gh api": "1\n2\n",
        }
    )

    bootstrap_plan.plan(runner, PROJECT, "000000-000000-000000", "owner/repo", TIMEOUT_S)

    assert not any("apply" in c[0] for c in runner.calls)


# ---------------------------------------------------------------- the runner itself


def test_run_returns_stdout_and_feeds_stdin() -> None:
    code = "import sys; sys.stdout.write(sys.stdin.read().upper())"

    assert _shell.run([sys.executable, "-c", code], "abc", TIMEOUT_S) == "ABC"


def test_run_failure_names_the_command_but_never_the_stdin() -> None:
    code = "import sys; sys.stdin.read(); sys.stderr.write('denied'); sys.exit(3)"

    with pytest.raises(_shell.CommandError) as caught:
        _shell.run([sys.executable, "-c", code], "the-secret", TIMEOUT_S)

    assert "exited 3" in str(caught.value)
    assert "denied" in str(caught.value)
    assert "the-secret" not in str(caught.value)


def test_run_timeout_is_a_command_error() -> None:
    with pytest.raises(_shell.CommandError, match="timed out"):
        _shell.run([sys.executable, "-c", "import time; time.sleep(5)"], None, 0.2)


def test_run_missing_binary_is_a_command_error() -> None:
    with pytest.raises(_shell.CommandError, match="could not start"):
        _shell.run(["/nonexistent/gcloud", "version"], None, TIMEOUT_S)


# ---------------------------------------------------------------- the secret store


def test_gcloud_secrets_checks_the_container_and_enabled_versions() -> None:
    runner = FakeRunner(answers={"versions list": "projects/p/secrets/x/versions/3\n"})
    store = _shell.GcloudSecrets(runner, PROJECT, TIMEOUT_S)

    store.ready("resend-api-key")
    assert store.has_value("resend-api-key") is True
    store.put("resend-api-key", SecretStr("token-1"))

    describe, listing, add = (c[0] for c in runner.calls)
    assert describe[:4] == ["gcloud", "secrets", "describe", "resend-api-key"]
    assert "--filter=state:ENABLED" in listing
    assert add[:4] == ["gcloud", "secrets", "versions", "add"]
    assert runner.calls[2][1] == "token-1"


def test_gcloud_secrets_without_versions_has_no_value() -> None:
    store = _shell.GcloudSecrets(FakeRunner(), PROJECT, TIMEOUT_S)

    assert store.has_value("resend-api-key") is False


def test_gcloud_secrets_missing_container_raises() -> None:
    store = _shell.GcloudSecrets(FakeRunner(fail="secrets describe"), PROJECT, TIMEOUT_S)

    with pytest.raises(_shell.CommandError):
        store.ready("resend-api-key")
