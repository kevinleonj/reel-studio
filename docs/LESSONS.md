# LESSONS — mistakes already made, and what now blocks each one

Add a row whenever a mistake happens. "Blocked by" names a test, hook or check, not a promise.

| # | Date | Mistake | Why it mattered | Blocked by |
|---|---|---|---|---|
| L1 | 8 Oct 2026 | Assumed the stock ffmpeg had `zscale` instead of checking | The HDR chain depends on it | Editor image build fails without `zscale` (STEP-02 task 5) |
| L2 | 8 Oct 2026 | Believed `allowed_tools` restricts the Agent SDK's tools; it only pre-approves | Wrong security claim | Product no longer uses the Agent SDK (D30); rule: prove behaviour with a test, not by reading one page |
| L3 | 9 Oct 2026 | Read only the Agent SDK overview and called hosting compliant; the legal page says otherwise | Business risk | Rule: for "may we host this", read the vendor's legal or terms pages (F01, F03) |
| L4 | 9 Oct 2026 | Planned `roles/run.invoker` to start the editor job with overrides; it lacks `run.jobs.runWithOverrides` | Start would fail in production | `roles/run.jobsExecutorWithOverrides` (F30); STEP-08 proves the start with runtime evidence |
| L5 | 9 Oct 2026 | Planned everything in Madrid; Cloud Scheduler is not offered there | Apply would fail late | `infra/policy/locations.toml` check (STEP-08 task 1) |
| L6 | 8 Oct 2026 | Used 100 images per request; 1M-context models allow 600, with a 2000 px rule above 20 | Wrong design limits | Tools resize every image to ≤ 2000 px (STEP-03 task 3) |
| L7 | 8 Oct 2026 | Planned 32 GiB at 4 vCPU; the maximum is 16 GiB | Apply would fail | Policy check on job resources (STEP-08 task 1) |
| L8 | 9 Oct 2026 | A total rounded from rounded parts ($1.34 instead of $1.33) | Wrong numbers erode trust | Meter test: no rounding inside the meter (STEP-03 task 4) |
| L9 | 9 Oct 2026 | Said "no API" for workspace spend limits without checking | Unverified claim | Rule: every "cannot" is a fact with a source, or marked unchecked |
| L10 | 9 Oct 2026 | The first guard hooks missed `grep -r`, quoted or globbed `.env`, `printenv VAR`, writing `.ci-pass`, pushing `HEAD:main` and `settings.local.json` | A guard that looks complete but is not | `selfcheck.py` keeps every bypass as a case (106 checks); regex guards are a seatbelt, not a security boundary |
| L11 | 9 Oct 2026 | Told Kevin to install keg-only Homebrew formulas (`ffmpeg-full`, `node@24`) without putting them on PATH | The checks would find the wrong ffmpeg | STEP-00 adds the PATH line and checks with `command -v` |
| L12 | 9 Oct 2026 | Planned the build on WSL without checking where Kevin's Claude Code, skills and logins live | An hour lost on a machine he does not use for this | D77: the Mac; `first-run.sh` checks the real tools first |
| L13 | 10 Oct 2026 | Piped a multi-line `--version` into `head -1` under `set -o pipefail` in `ci-install.d/cloud.sh`; the writer got SIGPIPE and CI stopped with exit 141 | The first CI run of the PR failed before `make ci` | `sed -n 1p` (reads all input) and the CI install step itself, which runs every lane script with pipefail |
| L14 | 10 Oct 2026 | Gave the deployer projectIamAdmin without a condition and let any main-branch job become it before approval; three reviews missed it | The deployer could grant itself roles/owner, and plan ran with its powers unapproved | `infra/bootstrap/tests/bootstrap.tftest.hcl` (conditional binding, environment-scoped impersonation), check_policy `conditional_roles` (iam.toml), `test_deploy_workflow.py` |
