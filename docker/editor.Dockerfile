# The editor image: `reel render` (STEP-02) and later the render job (STEP-05). D72:
# python:3.13-slim-trixie pinned by digest (F40, F200), Debian's ffmpeg with zscale (F45) checked
# at build time, linux/amd64 for Cloud Run, a non-root user.
#
#   make image-editor
#
# The digests are the multi-arch indexes looked up on 10 Oct 2026 (docs/FACTS.md F200, F205).
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:0.12.24@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a AS uv

FROM --platform=linux/amd64 python:3.13-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f

# Debian's ffmpeg is built with libzimg; fail the build if zscale is missing (F45): without it
# iPhone HDR clips come out washed out instead of failing loudly.
RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && ffmpeg -hide_banner -filters | grep -q ' zscale '

COPY --from=uv /uv /usr/local/bin/uv

RUN useradd --create-home --uid 10001 reel
WORKDIR /app
RUN chown reel:reel /app
USER reel

# Dependencies first, so a code change does not reinstall them; uv.lock decides every version.
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv
COPY --chown=reel:reel pyproject.toml uv.lock README.md ./
RUN uv sync --locked --extra editor --no-install-project
COPY --chown=reel:reel reel_studio ./reel_studio
COPY --chown=reel:reel config ./config
RUN uv sync --locked --extra editor

ENV PATH="/app/.venv/bin:${PATH}" \
    FFMPEG_PATH=/usr/bin/ffmpeg \
    FFPROBE_PATH=/usr/bin/ffprobe

ENTRYPOINT ["reel"]
CMD ["--help"]
