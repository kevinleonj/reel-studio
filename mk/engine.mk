# Lane engine owns this file (STEP-02 to 05).
.PHONY: ci-engine image-editor

# The media tests need an ffmpeg with zscale (F45); this prints which one they found: on the Mac
# Homebrew's keg-only ffmpeg-full, in CI Ubuntu's ffmpeg (F201). make ci runs it after the tests.
ci-engine:
	$(UV) python -c "from tests.fixtures.make_clips import find_tools; print('ci-engine: ffmpeg with zscale:', find_tools().ffmpeg)"

# The editor image (D72). Slow under emulation on Apple silicon; CI builds and runs it in
# tests/integration/editor/test_image.py.
image-editor:
	docker build --platform linux/amd64 -f docker/editor.Dockerfile -t reel-studio-editor .
