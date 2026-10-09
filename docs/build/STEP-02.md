# STEP-02 — The deterministic pipeline: render a Reel from an edit list

**Outcome:** `uv run reel render --edl <edl.json> <folder>` turns a folder of clips and a hand-written
edit list into `text.mp4` and `clean.mp4` that pass the hard checks. No model is called. This is the
old kit's media code moved into the package, with tests.

Lane **engine**: the worktree `~/projects/reel/reel-studio-engine` (`git rev-parse --show-toplevel` ends in
`/reel-studio-engine`); do not leave it. Handoff file: `docs/handoff/engine.md`.
Settled: D02, D38, D42, D43, D46 (port unchanged unless a failing test demands it), D72.
Source to port: `$OLD_KIT_DIR/scripts/` (`common`, `prep`, `shots`, `strip`, `grade`, `render`, `qa`,
`textcards`, `selftest`), `$OLD_KIT_DIR/claude-config/skills/make-reel/references/edl-schema.md`,
`$OLD_KIT_DIR/assets/fonts/` (Poppins Bold, OFL licence: keep `OFL.txt`).

## Discovery

```bash
git rev-parse --show-toplevel && git status --short
grep -o '^OLD_KIT_DIR=' .env                 # present
ffmpeg -hide_banner -filters | grep -c -E ' (zscale|tonemap) '   # 2
```
Branch `step-02-pipeline`.

## Tasks

1. **Synthetic fixtures, no binaries in git.** Port `selftest.py` into `tests/fixtures/make_clips.py`,
   which generates with ffmpeg: a portrait HEVC 10-bit HLG clip with rotation metadata (iPhone HDR), a
   60 fps clip with audio, a landscape clip without audio, a 90 s long take with a hard cut, a still
   photo. A session-scoped pytest fixture builds them once into a temp folder.
2. **Port the media modules** into `reel_studio/editor/media/` as functions with typed arguments
   (no `argparse`, no `print`; JSON logs per D74). Keep the kit's algorithms. Its constants move to
   `config/media.toml` (tunables: sizes, thresholds, encoder settings) or `reel_studio/core/constants.py`
   (format facts), each with a comment naming the kit file and line (D76); the scanner fails otherwise. One test
   module per file, written first:
   - `prepare`: proxy is 1080p SDR, rotation applied, HDR clip tonemapped (mean luma inside the kit's
     range), the original is deleted from the work folder after its proxy exists (one at a time);
   - `sheets`: 4×4 tiles of 384×216 = 1536×864 (D38), 2–6 frames per clip at scene changes, a legend
     maps tile → clip and time, near-duplicate frames dropped;
   - `strip`, `grade`: images ≤ 2000 px per side (F08);
   - `edl`: Pydantic models for the kit schema plus the v1 fields in `docs/EDITOR.md` §7; the kit's
     `render.py --check` rules become validators that return every violation, not the first;
   - `render`: both versions, 1080×1920, 30 fps, H.264, AAC, −14 LUFS (two-pass loudnorm as the kit);
     refuses `audio.music`;
   - `qa`: hard checks and the three review sheets (hook, cuts, overview), `qa.json` with a
     `hard_checks` object whose values are booleans (the gate requires all `true`).
3. **Input folders are never modified (D02).** Test: hash every file in the input folder before and
   after `reel render`; byte-identical. The CLI opens inputs read-only.
4. **CLI** `reel render --edl <file> <folder> [--out <dir>]` in `reel_studio/cli/reel.py`; outputs
   `text.mp4`, `clean.mp4` and `qa.json` in `--out`. `tests/fixtures/make_clips.py <dir>` is also a command
   line (the gate calls both).
5. **Docker image for the editor** (`docker/editor.Dockerfile`): `python:3.13-slim-trixie` pinned by
   digest (look the digest up; F40), Debian `ffmpeg`, a build step `ffmpeg -hide_banner -filters | grep -q zscale`
   that fails the build without it (F45), non-root user, `uv sync --locked --extra editor`,
   `--platform linux/amd64`. `make image-editor` builds it; a test runs `reel render` inside it on
   the fixtures (marked `slow`, run in CI).

## Done when

- `python3 scripts/gates/step02.py` prints `GATE step02 PASS` (run it in the background; paste the
  last 25 lines). It checks `make ci`, the literal scan, `docs/handoff/engine.md` and the pull request.
- `uv run reel render --edl tests/fixtures/edl/basic.json <fixtures>` output and `ffprobe` lines of
  both MP4s pasted (resolution, fps, codecs, duration).
- The hash test output (identical).
- Image size and build time recorded in HANDOFF.md.
- Definition of done (verbatim): Failing test existed, now passes; full suite green; CI Mirror Gate
  green. Runtime evidence pasted. Diff touches only the stated scope; no new dependency without a
  reason. No secret, no hard-coded client value; docs cited for every external API used.
  `HANDOFF.md` updated with before/after and follow-ups.
  (In a lane, that is `docs/handoff/engine.md`.)

STOP if a kit algorithm must change to pass a test: write the failing case in HANDOFF.md first.
Final message: five-line status board, then the PR link.
