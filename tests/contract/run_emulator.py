"""`make test-emulator`: start the pinned Firestore emulator and Mailpit containers, run the tests
marked `emulator` against them, stop them. Python, not shell, so it runs the same with the Mac's
bash 3.2.

    uv run --locked --all-extras python -m tests.contract.run_emulator [pytest args]
"""

import os
import smtplib
import subprocess
import sys
import time
from dataclasses import dataclass

import httpx

HOST = "127.0.0.1"
READY_TIMEOUT_S = 90
POLL_S = 1.0
HTTP_TIMEOUT_S = 2.0
DOCKER_TIMEOUT_S = 120


@dataclass(frozen=True)
class Service:
    name: str
    image: str  # pinned by digest (docs/FACTS.md F308, F309); same images as compose.yaml
    ports: tuple[int, ...]
    command: tuple[str, ...]
    ready_port: int


FIRESTORE_PORT = 8086
SMTP_PORT = 1026
MAILPIT_HTTP_PORT = 8026
SERVICES = (
    Service(
        "reel-studio-test-firestore",
        "gcr.io/google.com/cloudsdktool/google-cloud-cli"
        "@sha256:be2f0e582a94c9e06e7a384fe2b3b39d590eeb8da65a110eda991598c100fe80",
        (FIRESTORE_PORT,),
        ("gcloud", "emulators", "firestore", "start", f"--host-port=0.0.0.0:{FIRESTORE_PORT}"),
        FIRESTORE_PORT,
    ),
    Service(
        "reel-studio-test-mailpit",
        "axllent/mailpit@sha256:b68349e3a014b90c5610bfb26b2ae36f3892d7b8cf25ee140c6c71c98d2fcf48",
        (SMTP_PORT, MAILPIT_HTTP_PORT),
        ("--smtp", f"0.0.0.0:{SMTP_PORT}", "--listen", f"0.0.0.0:{MAILPIT_HTTP_PORT}"),
        MAILPIT_HTTP_PORT,
    ),
)


def docker(*args: str) -> None:
    subprocess.run(["docker", *args], check=True, timeout=DOCKER_TIMEOUT_S)  # noqa: S603, S607


def wait_ready(port: int) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            if (
                httpx.get(f"http://{HOST}:{port}/", timeout=HTTP_TIMEOUT_S).status_code
                == httpx.codes.OK
            ):
                return
        except httpx.TransportError:
            pass  # not listening yet; try again until the deadline
        time.sleep(POLL_S)
    raise SystemExit(f"service on {HOST}:{port} not ready after {READY_TIMEOUT_S} s")


def wait_smtp(port: int) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            with smtplib.SMTP(HOST, port, timeout=HTTP_TIMEOUT_S) as smtp:
                smtp.noop()
            return
        except (OSError, smtplib.SMTPException):
            time.sleep(POLL_S)  # not greeting yet; try again until the deadline
    raise SystemExit(f"SMTP on {HOST}:{port} not ready after {READY_TIMEOUT_S} s")


def main() -> int:
    started: list[str] = []
    try:
        for service in SERVICES:
            publish = [arg for port in service.ports for arg in ("-p", f"{HOST}:{port}:{port}")]
            docker(
                "run",
                "-d",
                "--rm",
                "--name",
                service.name,
                *publish,
                service.image,
                *service.command,
            )
            started.append(service.name)
        for service in SERVICES:
            wait_ready(service.ready_port)
        wait_smtp(SMTP_PORT)  # Mailpit's HTTP side can answer before its SMTP side greets
        env = {
            **os.environ,
            "FIRESTORE_EMULATOR_HOST": f"{HOST}:{FIRESTORE_PORT}",
            "MAILPIT_HOST": f"{HOST}:{SMTP_PORT},{MAILPIT_HTTP_PORT}",
            "REEL_REQUIRE_EMULATOR": "1",  # every emulator case must run, none may skip
        }
        cmd = [sys.executable, "-m", "pytest", "-q", "-m", "emulator", *sys.argv[1:]]
        return subprocess.run(cmd, env=env, check=False).returncode  # noqa: S603
    finally:
        for name in started:
            docker("stop", name)


if __name__ == "__main__":
    raise SystemExit(main())
