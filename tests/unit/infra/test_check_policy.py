"""scripts/check_policy.py (STEP-08 task 1): each rule fails on a bad fixture.

The fixtures are copies of the real infra/ with one deliberate defect each, so the checker is
proven against the code it guards, not against toy files.
"""

import shutil
from pathlib import Path

import pytest

from scripts import check_policy

INFRA = Path(__file__).resolve().parents[3] / "infra"


@pytest.fixture
def infra(tmp_path: Path) -> Path:
    target = tmp_path / "infra"
    shutil.copytree(INFRA, target, ignore=shutil.ignore_patterns(".terraform", "*.tfstate*"))
    return target


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"fixture anchor not unique in {path.name}: {old!r}"
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_repository_infra_passes(infra: Path) -> None:
    assert check_policy.run(infra) == []


def test_empty_infra_is_a_violation(tmp_path: Path) -> None:
    (tmp_path / "policy").mkdir()
    shutil.copytree(INFRA / "policy", tmp_path / "policy", dirs_exist_ok=True)
    assert check_policy.run(tmp_path) == ["infra: no Terraform root found"]


BAD = {
    # explicit_args.toml: a cost-relevant argument left to the provider default
    "missing argument": (
        "main/run.tf",
        "      max_retries     = local.editor_max_retries\n",
        "",
        "google_cloud_run_v2_job.editor: missing template.template.max_retries",
    ),
    # locations.toml, lesson L5: Cloud Scheduler is not offered in Madrid
    "wrong region": (
        "main/scheduler.tf",
        "  region           = local.region\n",
        '  region           = "europe-southwest1"\n',
        "google_cloud_scheduler_job.sweep: region europe-southwest1 not allowed (europe-west1)",
    ),
    # limits.toml, lesson L7: 32 GiB was planned at 4 vCPU; the maximum is 16 GiB
    "job memory above the maximum": (
        "main/locals.tf",
        '  editor_memory      = "16Gi"',
        '  editor_memory      = "32Gi"',
        "google_cloud_run_v2_job.editor: memory 32Gi above 16Gi at 4 vCPU",
    ),
    # limits.toml, D52: a retry pays Claude twice
    "job retries": (
        "main/locals.tf",
        "  editor_max_retries = 0",
        "  editor_max_retries = 1",
        "google_cloud_run_v2_job.editor: max_retries 1, must be 0",
    ),
    # explicit_args.toml depends_on: creating the job needs the deployer's actAs grant first
    "missing ordering": (
        "main/scheduler.tf",
        "  depends_on = [google_project_service.runtime,"
        " google_service_account_iam_member.deployer_acts_as]\n",
        "  depends_on = [google_project_service.runtime]\n",
        "google_cloud_scheduler_job.sweep: depends_on lacks"
        " google_service_account_iam_member.deployer_acts_as",
    ),
    # iam.toml, REVIEW-FIXES CLOUD 1a: projectIamAdmin without a condition can grant roles/owner
    "unconditional project IAM admin": (
        "bootstrap/locals.tf",
        '    "roles/logging.configWriter",\n',
        '    "roles/logging.configWriter",\n    "roles/resourcemanager.projectIamAdmin",\n',
        "google_project_iam_member.deployer: roles/resourcemanager.projectIamAdmin granted"
        " without a condition",
    ),
    # STEP-08 task 4: the service URL comes from the project number (F61)
    "service uri": (
        "main/outputs.tf",
        "  value       = local.service_url\n",
        "  value       = google_cloud_run_v2_service.api.uri\n",
        "main/outputs.tf: google_cloud_run_v2_service.api.uri used; build the URL from the project"
        " number (F61)",
    ),
}


@pytest.mark.parametrize("case", sorted(BAD))
def test_bad_fixture_fails(infra: Path, case: str) -> None:
    relative, old, new, expected = BAD[case]
    edit(infra / relative, old, new)
    assert expected in check_policy.run(infra)


def test_many_defects_are_all_reported_sorted(infra: Path) -> None:
    for case in ("wrong region", "job retries"):
        relative, old, new, _ = BAD[case]
        edit(infra / relative, old, new)
    found = check_policy.run(infra)
    assert found == sorted(found)
    assert [BAD["job retries"][3], BAD["wrong region"][3]] == [
        line for line in found if line in {BAD["job retries"][3], BAD["wrong region"][3]}
    ]


def test_unparseable_terraform_exits_2(infra: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (infra / "main" / "broken.tf").write_text('resource "x" {\n', encoding="utf-8")
    assert check_policy.main(["--infra", str(infra)]) == check_policy.EXIT_ERROR
    assert "cannot parse" in capsys.readouterr().err


def test_main_exit_codes(infra: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert check_policy.main(["--infra", str(infra)]) == check_policy.EXIT_CLEAN
    assert "policy: 0 violations" in capsys.readouterr().out
    relative, old, new, expected = BAD["job retries"]
    edit(infra / relative, old, new)
    assert check_policy.main(["--infra", str(infra)]) == check_policy.EXIT_FOUND
    assert expected in capsys.readouterr().out
