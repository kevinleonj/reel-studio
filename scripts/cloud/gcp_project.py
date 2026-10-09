"""`make gcp-project`: create the project, link billing, enable the APIs Terraform starts with.

Uses Kevin's gcloud login (docs/INFRA.md §3). Safe to run twice: an existing project is kept and
only the billing link and API list are re-applied (both are idempotent in gcloud).
"""

import sys
from collections.abc import Sequence

from reel_studio.core.config import load_cloud
from reel_studio.settings import CloudSettings
from scripts.cloud._shell import CommandError, Runner, run, say


def exists(runner: Runner, project: str, timeout_s: float) -> bool:
    try:
        runner(["gcloud", "projects", "describe", project, "--format=json"], None, timeout_s)
    except CommandError:
        return False  # describe fails for a project that does not exist or is not visible
    return True


def ensure_project(
    runner: Runner,
    project: str,
    billing_account: str,
    services: Sequence[str],
    timeout_s: float,
) -> None:
    if exists(runner, project, timeout_s):
        say(f"gcp-project: {project} exists, kept")
    else:
        runner(["gcloud", "projects", "create", project, "--quiet"], None, timeout_s)
        say(f"gcp-project: {project} created")
    runner(
        [
            "gcloud",
            "billing",
            "projects",
            "link",
            project,
            f"--billing-account={billing_account}",
        ],
        None,
        timeout_s,
    )
    say("gcp-project: billing linked")
    runner(["gcloud", "services", "enable", *services, f"--project={project}"], None, timeout_s)
    say(f"gcp-project: enabled {', '.join(services)}")


def main() -> int:
    settings = CloudSettings()
    cloud = load_cloud()
    try:
        ensure_project(
            run,
            settings.gcp_project,
            settings.gcp_billing_account,
            cloud.gcp_project.bootstrap_services,
            cloud.gcloud.timeout_s,
        )
    except CommandError as exc:
        say(f"gcp-project: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
