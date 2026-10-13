"""Local state and Terraform leftovers stay out of git wherever they are written (web.md and
cloud.md, For MAIN)."""

import shutil
import subprocess
from pathlib import Path

GIT = shutil.which("git")
GIT_TIMEOUT_S = 30  # a local index lookup; anything near this is a hung git
ROOT = Path(__file__).resolve().parents[2]
# A hook writes .claude/state/ under the session's working directory, which may be web/ (L305).
MUST_IGNORE = (
    ".claude/state/session.json",
    "web/.claude/state/session.json",
    "infra/main/.claude/state/session.json",
    "prod.tfvars",
    "prod.tfvars.json",
    "infra/main/beta.tfvars",
    "tfplan.json",
    "infra/main/tfplan.json",
    "crash.log",
)


def _ignored(path: str) -> bool:
    # --no-index: judge the pattern even if a file of that name were tracked.
    assert GIT is not None, "git is not on PATH"
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [GIT, "check-ignore", "--no-index", "--quiet", path],
        cwd=ROOT,
        check=False,
        timeout=GIT_TIMEOUT_S,
    )
    # 0 ignored, 1 not ignored; anything else (not a repository, a bad path) is an error.
    assert result.returncode in (0, 1), f"git check-ignore failed with {result.returncode}"
    return result.returncode == 0


def test_local_state_and_terraform_leftovers_are_ignored() -> None:
    assert [path for path in MUST_IGNORE if not _ignored(path)] == []


def test_the_env_example_and_terraform_sources_stay_tracked() -> None:
    assert [p for p in (".env.example", "infra/main/run.tf") if _ignored(p)] == []
