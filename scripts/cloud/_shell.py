"""Shared pieces of the STEP-08 setup scripts: running gcloud, terraform and gh, and output.

A secret only ever travels on a subprocess's stdin, never in its arguments, and an error message
names the command and its exit code, never what was piped into it.
"""

import subprocess
import sys
from collections.abc import Callable, Sequence
from typing import Protocol

from pydantic import SecretStr

STDERR_TAIL_CHARS = 400  # enough to see gcloud's reason, short enough to keep logs readable
# F61: Cloud Run's deterministic URL, known before the service exists.
SERVICE_URL = "https://{service}-{number}.{region}.run.app"
SERVICE_NAME = "reel-api"  # infra/main/locals.tf api_name

Runner = Callable[[Sequence[str], str | None, float], str]


class CommandError(Exception):
    """A command exited non-zero or timed out; the message never contains its stdin."""


def run(args: Sequence[str], stdin: str | None, timeout_s: float) -> str:
    """Run one command with a timeout; returns stdout, raises CommandError otherwise."""
    shown = " ".join(args[:3])
    try:
        done = subprocess.run(
            list(args),
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CommandError(f"{shown} timed out after {timeout_s} s") from exc
    except OSError as exc:
        raise CommandError(f"{shown} could not start: {exc.strerror}") from exc
    if done.returncode != 0:
        tail = done.stderr.strip()[-STDERR_TAIL_CHARS:]
        raise CommandError(f"{shown} exited {done.returncode}: {tail}")
    return done.stdout


def push_secret(
    runner: Runner, project: str, secret_id: str, value: SecretStr, timeout_s: float
) -> None:
    """Add a version to a Secret Manager container created by infra/bootstrap."""
    raw = value.get_secret_value()
    if not raw:
        raise ValueError(f"{secret_id}: refusing to store an empty secret")
    runner(
        [
            "gcloud",
            "secrets",
            "versions",
            "add",
            secret_id,
            "--data-file=-",
            f"--project={project}",
        ],
        raw,
        timeout_s,
    )


def version_id(name: str) -> str:
    """`projects/p/secrets/s/versions/7` -> `7`."""
    return name.strip().rsplit("/", 1)[-1]


def rotate_secret(
    runner: Runner, project: str, secret_id: str, value: SecretStr, timeout_s: float
) -> str:
    """Add a version, confirm it is ENABLED, then destroy the older versions still billed.

    Enabled and disabled versions are both billed and the old value stays readable; destroyed
    versions are free (F413). Nothing is destroyed unless the new version is confirmed.
    """
    raw = value.get_secret_value()
    if not raw:
        raise ValueError(f"{secret_id}: refusing to store an empty secret")
    where = f"--project={project}"
    added = runner(
        [
            "gcloud",
            "secrets",
            "versions",
            "add",
            secret_id,
            "--data-file=-",
            where,
            "--format=value(name)",
        ],
        raw,
        timeout_s,
    )
    new = version_id(added)
    state = runner(
        [
            "gcloud",
            "secrets",
            "versions",
            "describe",
            new,
            f"--secret={secret_id}",
            where,
            "--format=value(state)",
        ],
        None,
        timeout_s,
    ).strip()
    if not new.isdigit() or state != "ENABLED":
        raise CommandError(
            f"{secret_id}: new version {new or '?'} is {state or 'missing'}; older versions kept"
        )
    listed = runner(
        [
            "gcloud",
            "secrets",
            "versions",
            "list",
            secret_id,
            where,
            "--filter=NOT state:DESTROYED",
            "--format=value(name)",
        ],
        None,
        timeout_s,
    )
    # Only versions older than ours: a newer one may come from another writer and must survive.
    older = {
        v
        for v in (version_id(name) for name in listed.split())
        if v.isdigit() and int(v) < int(new)
    }
    for old in sorted(older, key=int):
        runner(
            [
                "gcloud",
                "secrets",
                "versions",
                "destroy",
                old,
                f"--secret={secret_id}",
                where,
                "--quiet",
            ],
            None,
            timeout_s,
        )
    return new


class SecretStore(Protocol):
    """Where show-once secrets go. Check `ready` before asking a vendor to mint one."""

    def ready(self, secret_id: str) -> None: ...
    def has_value(self, secret_id: str) -> bool: ...
    def put(self, secret_id: str, value: SecretStr) -> None: ...


class GcloudSecrets:
    """Secret Manager through Kevin's gcloud login; values only on stdin."""

    def __init__(self, runner: Runner, project: str, timeout_s: float) -> None:
        self._runner = runner
        self._project = project
        self._timeout_s = timeout_s

    def ready(self, secret_id: str) -> None:
        """Raises CommandError when the container does not exist (bootstrap not applied)."""
        self._runner(
            ["gcloud", "secrets", "describe", secret_id, f"--project={self._project}"],
            None,
            self._timeout_s,
        )

    def has_value(self, secret_id: str) -> bool:
        out = self._runner(
            [
                "gcloud",
                "secrets",
                "versions",
                "list",
                secret_id,
                f"--project={self._project}",
                "--filter=state:ENABLED",
                "--limit=1",
                "--format=value(name)",
            ],
            None,
            self._timeout_s,
        )
        return bool(out.strip())

    def put(self, secret_id: str, value: SecretStr) -> None:
        push_secret(self._runner, self._project, secret_id, value, self._timeout_s)


def service_url(number: str, region: str) -> str:
    return SERVICE_URL.format(service=SERVICE_NAME, number=number, region=region)


def say(message: str) -> None:
    sys.stdout.write(f"{message}\n")
