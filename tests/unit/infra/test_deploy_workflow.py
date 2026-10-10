"""The deploy workflow's security settings (docs/INFRA.md §4, REVIEW-FIXES CLOUD items 1 and 5).

Read as text: no YAML parser is a declared dependency, and these are line-level settings.
"""

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "deploy.yml"


def job(name: str) -> str:
    """The text of one job, from its `  name:` line to the next job or the end."""
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index(f"\n  {name}:\n")
    rest = text[start + 1 :]
    following = [rest.find(f"\n  {other}:\n") for other in ("plan", "apply") if other != name]
    ends = [i for i in following if i > 0]
    return rest[: min(ends)] if ends else rest


def test_every_job_that_can_mint_a_token_waits_for_the_beta_environment() -> None:
    # The deployer is bound to attribute.environment/beta, so a job that asks for an id-token
    # without the environment could not become the deployer, and must not try.
    for name in ("plan", "apply"):
        text = job(name)
        assert "id-token: write" in text, name
        assert "environment: beta" in text, name
