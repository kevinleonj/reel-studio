# Lane engine owns this file (STEP-02 to 05).
.PHONY: ci-engine image-editor eval ab ab-pick

# The media tests need an ffmpeg with zscale (F45); this prints which one they found: on the Mac
# Homebrew's keg-only ffmpeg-full, in CI Ubuntu's ffmpeg (F201). make ci runs it after the tests.
ci-engine:
	$(UV) python -c "from tests.fixtures.make_clips import find_tools; print('ci-engine: ffmpeg with zscale:', find_tools().ffmpeg)"

# The editor image (D72). Slow under emulation on Apple silicon; CI builds and runs it in
# tests/integration/editor/test_image.py.
image-editor:
	docker build --platform linux/amd64 -f docker/editor.Dockerfile -t reel-studio-editor .

# One paid run of `reel make` on REEL_FIXTURES_DIR/$(FIX), recorded in eval/results/<date>/
# (STEP-03 task 8). MODEL=haiku proves the plumbing for cents; the default is Sonnet.
MODEL ?= sonnet
eval:
	@test -n "$(FIX)" || { echo "usage: make eval FIX=<fixture> [MODEL=haiku]"; exit 2; }
	$(UV) python -m reel_studio.editor.evaluate --fixture $(FIX) --model $(MODEL)

# STEP-04: both engines on the fixtures in limits.toml [eval.ab], judged by our critic, inside the
# step budget (ONLY=a,b limits it; REDO=a,b reruns their finished arms after a tune,
# REDO=a:new only our engine's arm);
# then Kevin's blind picks turn
# eval/results/<date>/ab-runs.json into ab.json.
ONLY ?=
REDO ?=
ab:
	$(UV) python -m reel_studio.editor.ab --only "$(ONLY)" --redo "$(REDO)"

ab-pick:
	$(UV) python -m reel_studio.editor.ab_pick
