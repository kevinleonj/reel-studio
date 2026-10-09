"""Shared pieces of the STEP-08 setup scripts: running gcloud, terraform and gh, and output.

A secret only ever travels on a subprocess's stdin, never in its arguments, and an error message
names the command and its exit code, never what was piped into it.
"""

import subprocess
import sys
from collections.abc import Callable, Sequence

from pydantic import SecretStr

STDERR_TAIL_CHARS = 400  # enough to see gcloud's reason, short enough to keep logs readable
# F61: Cloud Run's deterministic URL, known before the service exists.
SERVICE_URL = "https://{service}-{number}.{region}.run.app"
SERVICE_NAME = "reel-api"  # infra/main/locals.tf api_name

Runner = Callable[[Sequence[str], str | None, float], str]
SecretSink = Callable[[str, SecretStr], None]


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


def secret_sink(runner: Runner, project: str, timeout_s: float) -> SecretSink:
    """push_secret bound to one project, for code that only decides what to store."""

    def store(secret_id: str, value: SecretStr) -> None:
        push_secret(runner, project, secret_id, value, timeout_s)

    return store


def service_url(number: str, region: str) -> str:
    return SERVICE_URL.format(service=SERVICE_NAME, number=number, region=region)


def say(message: str) -> None:
    sys.stdout.write(f"{message}\n")
