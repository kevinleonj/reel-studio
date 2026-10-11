# reel-api: the FastAPI app serving the Astro site, and (same image, other command) the laptop
# dispatcher. STEP-06 task 6; linux/amd64 for Cloud Run (STEP-08), a non-root user.
#
#   make up        builds it through compose.yaml
#
# Digests are the multi-arch indexes: node 24.21.0 looked up on 11 Oct 2026 (docs/FACTS.md F314),
# uv and python as in docker/editor.Dockerfile (F200, F205).
# The site is static output, so this stage runs natively on the build machine.
FROM --platform=$BUILDPLATFORM node:24.21.0-trixie-slim@sha256:173f125896c3b47ddf056734c7ea789d04595a6a08769a8f78e0df642781fb66 AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/astro.config.mjs web/tsconfig.json web/components.json ./
COPY web/src ./src
COPY web/public ./public
# Canonical links, sitemap and robots.txt carry it (astro.config.mjs); compose passes .env's value.
ARG SITE_URL
RUN test -n "$SITE_URL" || { echo "build arg SITE_URL is required (compose passes .env's)" >&2; exit 1; } \
    && SITE_URL="$SITE_URL" npx astro build

FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:0.12.24@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a AS uv

FROM --platform=linux/amd64 python:3.13-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f

COPY --from=uv /uv /usr/local/bin/uv

RUN useradd --create-home --uid 10001 reel
WORKDIR /app
RUN chown 10001:10001 /app
USER 10001:10001

# Dependencies first, so a code change does not reinstall them; uv.lock decides every version.
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv UV_NO_CACHE=1
COPY --chown=10001:10001 pyproject.toml uv.lock README.md ./
RUN uv sync --locked --extra api --no-install-project
COPY --chown=10001:10001 reel_studio ./reel_studio
COPY --chown=10001:10001 config ./config
RUN uv sync --locked --extra api
# The API's user messages come from the site's one copy table (reel_studio/api/messages.py).
COPY --chown=10001:10001 web/src/copy/en.json ./web/src/copy/en.json
COPY --from=web --chown=10001:10001 /web/dist ./web/dist

ENV PATH="/app/.venv/bin:${PATH}"
EXPOSE 8080
# --no-access-log: uvicorn's access log prints the path and query (signed-link `sig=`, Stripe's
# `?t=`); the app logs every request itself with the route template only.
CMD ["uvicorn", "--factory", "reel_studio.api.main:create", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
