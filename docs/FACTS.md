# FACTS — every vendor number and rule the code relies on

Rules for this file:
- One row per fact. Code and config cite the fact ID (for example `# F05`).
- A fact without a URL and an access date is not a fact. Re-verify before relying on anything older than 30 days.
- "Status" is `verified` (page opened and quoted), `measured` (our own run), `conflicting` (sources disagree: test it) or `UNCONFIRMED`.
- Claude Code: when you look something up (Context7 or a vendor page), add or update the row here in the same commit.

Snapshot: 9 Oct 2026 unless the row says otherwise.

## Anthropic

| ID | Fact | Value | Source | Accessed | Status |
|---|---|---|---|---|---|
| F01 | Running Claude Code inside a product: end-user condition | "Customers may not pay for, resell, or intermediate Claude usage on their end users' behalf. Each end user must authenticate with their own Anthropic API key" | https://code.claude.com/docs/en/legal-and-compliance | 9 Oct 2026 | verified |
| F02 | What the Agent SDK is | "A library that runs the Claude Code binary" | https://code.claude.com/docs/en/agent-sdk/overview | 9 Oct 2026 | verified |
| F03 | Commercial Terms clauses that apply to Reel Studio | A.1 power products for "its own customers and end users"; D.3 tell users outputs may be inaccurate; D.4 no reselling the Services | https://www.anthropic.com/legal/commercial-terms | 9 Oct 2026 | verified |
| F04 | Model IDs, context, output | `claude-sonnet-5-5`, `claude-haiku-5-5` (alias = ID); both 1M-token context, 128K max output | https://platform.claude.com/docs/en/models/overview | 9 Oct 2026 | verified |
| F05 | Prices per million tokens | Sonnet 5.5: input $2, 5-min cache write $2.50, cache read $0.10, output $10. Haiku 5.5 prompt ≤100,000 tokens: $0.10 / $0.125 / $0.01 / $0.50; prompt >100,000: $0.50 / $0.625 / $0.05 / $2.50 | https://platform.claude.com/docs/en/about-claude/pricing | 9 Oct 2026 | verified |
| F06 | Python SDK | `anthropic` 1.13.0 (resolved by `uv add` into uv.lock), requires Python ≥3.10 | https://pypi.org/pypi/anthropic/json , uv.lock | 9 Oct 2026 | verified |
| F07 | Prompt caching | Top-level `cache_control` (automatic) needs no beta header; max 4 breakpoints (automatic uses one); minimum 512 tokens on Sonnet 5.5, shorter prompts are silently not cached; default lifetime 5 minutes, refreshed on use | https://platform.claude.com/docs/en/build-with-claude/prompt-caching | 9 Oct 2026 | verified |
| F08 | Vision limits | 600 images per request (non-200K models); max 8000×8000 px; above 20 images every image ≤2000 px per side, images in `tool_result` count; 32 MB per request; tokens = ⌈w/28⌉ × ⌈h/28⌉ | https://platform.claude.com/docs/en/build-with-claude/vision | 9 Oct 2026 | verified |
| F09 | Images in tool results | `tool_result` content may hold `text`, `image`, `document`, `search_result` blocks | https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls | 9 Oct 2026 | verified |
| F10 | Forcing a tool | `tool_choice` `any` and `tool` return HTTP 400 on Claude Sonnet 5.5 | https://platform.claude.com/docs/en/agents-and-tools/tool-use/implement-tool-use | 9 Oct 2026 | verified |
| F11 | Strict tools and structured outputs | Generally available, no beta header; `strict: true` on the tool definition; JSON Schema subset without numeric or length constraints, `additionalProperties: false` required | https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use , https://platform.claude.com/docs/en/build-with-claude/structured-outputs | 9 Oct 2026 | verified |
| F12 | Tool result ordering | One `tool_result` per `tool_use`, all together in the next user message, before any text | https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls , https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use | 9 Oct 2026 | verified |
| F13 | Spend limit errors | Workspace limit you set: HTTP 400 `invalid_request_error`, message begins "You have reached your specified workspace API usage limits". Default Workspace cannot have limits. Organisation tier cap: HTTP 429 `enforced_spend_limit_reached` | https://platform.claude.com/docs/en/api/rate-limits | 9 Oct 2026 | verified |
| F14 | Token counting | Free; own rate limit (Start tier 5,000 requests per minute) | https://platform.claude.com/docs/en/build-with-claude/token-counting | 9 Oct 2026 | verified |
| F15 | SDK retries | 2 retries by default with backoff on connection errors, 408, 409, 429, ≥500; `Anthropic(max_retries=...)` | https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python | 9 Oct 2026 | verified |
| F16 | Effort | `output_config.effort`: max, xhigh, high, medium, low; Sonnet 5.5 default `high`; docs suggest starting multistep tool use at `medium` | https://platform.claude.com/docs/en/build-with-claude/effort | 9 Oct 2026 | verified |
| F17 | Tool runner | Beta in every SDK; the page points to the manual loop for "custom logging, or conditional execution" | https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-runner | 9 Oct 2026 | verified |
| F18 | Cache invalidation by output format | "Changing the output_config.format parameter will invalidate any prompt cache for that conversation thread" | https://platform.claude.com/docs/en/build-with-claude/structured-outputs | 9 Oct 2026 | verified |

## Stripe and Resend

| ID | Fact | Value | Source | Accessed | Status |
|---|---|---|---|---|---|
| F19 | SDK and API version | `stripe` 16.0.0 (1 Oct 2026); API version `2026-09-30.endive` | https://pypi.org/pypi/stripe/json , https://docs.stripe.com/changelog | 9 Oct 2026 | verified |
| F20 | Checkout Session expiry | `expires_at` 30 minutes to 24 hours after creation; default 24 hours | https://docs.stripe.com/api/checkout/sessions/create | 9 Oct 2026 | verified |
| F21 | Server-side promotion code | `discounts=[{"promotion_code": "promo_..."}]`, at most one; find the ID with List promotion codes `code=` (case-insensitive) | https://docs.stripe.com/api/checkout/sessions/create , https://docs.stripe.com/api/promotion_codes/list | 9 Oct 2026 | verified |
| F21b | `discounts` together with `allow_promotion_codes` | Not stated anywhere; we never send both | https://docs.stripe.com/payments/checkout/discounts | 9 Oct 2026 | UNCONFIRMED |
| F22 | No-cost orders | Total 0 → no payment method collected; `mode=payment`; API version 2023-08-16 or later | https://docs.stripe.com/payments/checkout/no-cost-orders | 9 Oct 2026 | verified |
| F23 | Webhooks | `checkout.session.completed` and `checkout.session.expired` exist; the same event may arrive more than once; verify the `Stripe-Signature` header with the endpoint secret | https://docs.stripe.com/webhooks , https://docs.stripe.com/api/events/types | 9 Oct 2026 | verified |
| F24 | Fulfilment | Fulfil from the webhook and from the landing page, idempotently | https://docs.stripe.com/checkout/fulfillment | 8 Oct 2026 | verified |
| F25 | Resend | `resend` 2.49.1; free plan 3,000 emails a month, 100 a day; sending to other people needs a verified domain | https://pypi.org/pypi/resend/json , https://resend.com/pricing , https://resend.com/docs/knowledge-base/403-error-resend-dev-domain | 9 Oct 2026 | verified |

## Google Cloud and Gemini

| ID | Fact | Value | Source | Accessed | Status |
|---|---|---|---|---|---|
| F26 | Cloud Scheduler regions | europe-west1 offered; europe-southwest1 not listed | https://docs.cloud.google.com/scheduler/docs/locations | 9 Oct 2026 | verified |
| F27 | Cloud Run price tier | europe-west1 and europe-southwest1 are both Tier 1 | https://docs.cloud.google.com/run/docs/locations , https://cloud.google.com/run/pricing | 9 Oct 2026 | verified |
| F28 | Firestore location | europe-west1 is a regional location | https://docs.cloud.google.com/firestore/native/docs/locations | 9 Oct 2026 | verified |
| F29 | Cloud Run job limits | Default task timeout 10 min, max 168 h; default retries 3 (range 0–10); max 8 vCPU and 32 GiB; at 4 vCPU memory 2–16 GiB | https://docs.cloud.google.com/run/docs/configuring/task-timeout , https://docs.cloud.google.com/run/docs/configuring/max-retries , https://docs.cloud.google.com/run/docs/configuring/jobs/memory-limits | 9 Oct 2026 | verified |
| F30 | Running a job with overrides | Needs `run.jobs.runWithOverrides`; `roles/run.invoker` lacks it; narrowest role `roles/run.jobsExecutorWithOverrides` | https://docs.cloud.google.com/run/docs/execute/jobs , https://docs.cloud.google.com/run/docs/reference/iam/roles | 9 Oct 2026 | verified |
| F31 | Cloud Run request limits | HTTP/1 request 32 MiB; request timeout up to 60 min | https://docs.cloud.google.com/run/quotas | 9 Oct 2026 | verified |
| F32 | Resumable uploads from a browser | Session URI valid one week; pass the browser's Origin when creating the session; XML API CORS comes from the bucket configuration | https://docs.cloud.google.com/storage/docs/resumable-uploads , https://docs.cloud.google.com/storage/docs/cross-origin | 9 Oct 2026 | verified |
| F33 | Python call that creates the session | `Blob.create_resumable_upload_session(content_type, size, origin, ...)`; `size` caps the bytes; `origin` binds the browser origin | Context7 `/googleapis/python-storage` | 9 Oct 2026 | verified |
| F34 | Signing download URLs without a key file | Needs `iam.serviceAccounts.signBlob` (`roles/iam.serviceAccountTokenCreator`); Google's guide says grant on the project, the Python reference disagrees on GCE accounts | https://docs.cloud.google.com/storage/docs/access-control/signing-urls-with-helpers , https://docs.cloud.google.com/python/docs/reference/storage/latest/google.cloud.storage.blob.Blob | 9 Oct 2026 | conflicting: prove by signing in step 8 |
| F35 | Firestore free quota | Per day: 1 GiB stored, 50,000 reads, 20,000 writes, 20,000 deletes; only the `(default)` database | https://cloud.google.com/firestore/pricing | 9 Oct 2026 | verified |
| F36 | Terraform versions | Terraform 1.16.5 (2 Oct 2026); `hashicorp/google` 8.6.0 (6 Oct 2026) | https://api.releases.hashicorp.com/v1/releases/terraform , https://registry.terraform.io/v1/providers/hashicorp/google | 9 Oct 2026 | verified |
| F37 | Gemini transcription | Model `gemini-3.5-transcribe`; about $0.005 per minute; word-level timestamps supported, audio capped at 30 min when on; Spanish (Spain) `es-ES` not in the language table (es-419, es-US are) | https://ai.google.dev/gemini-api/docs/transcribe , https://ai.google.dev/gemini-api/docs/pricing | 9 Oct 2026 | verified (es-ES conflicting: test) |
| F38 | Gemini SDK | `google-genai` 2.29.0 (7 Oct 2026), Python ≥3.10 | https://pypi.org/pypi/google-genai/json | 9 Oct 2026 | verified |
| F46 | Custom domain on Cloud Run | Domain mapping is Preview, "not production-ready", available in europe-west1; global load balancer recommended | https://docs.cloud.google.com/run/docs/mapping-custom-domains | 9 Oct 2026 | verified |
| F47 | Cost of a load balancer + Cloud Armor | Forwarding rule $0.025/h ≈ $18.25/month, policy $5, rule $1 → about $24/month before traffic | https://cloud.google.com/armor/pricing , https://cloud.google.com/vpc/network-pricing | 9 Oct 2026 | verified |
| F49 | Cloud Run jobs price (Tier 1) | $0.000018 per vCPU-second, $0.000002 per GiB-second; free 240,000 vCPU-s and 450,000 GiB-s per month | https://cloud.google.com/run/pricing | 8 Oct 2026 | verified |
| F50 | Cloud Storage soft delete | On by default for 7 days and billed | https://docs.cloud.google.com/storage/docs/soft-delete | 8 Oct 2026 | verified |
| F51 | Firestore transactions | Lock the documents they read and retry on contention | https://docs.cloud.google.com/firestore/native/docs/transaction-data-contention | 9 Oct 2026 | verified |
| F61 | Cloud Run deterministic URL | `https://SERVICE_NAME-PROJECT_NUMBER.REGION.run.app`, "lets you predict the service URL before the service is created", if the DNS segment is ≤ 63 characters | https://docs.cloud.google.com/run/docs/triggering/https-request | 9 Oct 2026 | verified |
| F52 | Max instances | Google describes max instances as a cost-safety limit | https://docs.cloud.google.com/run/docs/configuring/max-instances | 9 Oct 2026 | verified |

## Tooling

| ID | Fact | Value | Source | Accessed | Status |
|---|---|---|---|---|---|
| F62 | Astro | 7.3.8 (published 8 Oct 2026); requires Node `>=22.12.0`; pin the exact version (7.3.7 and 7.3.8 shipped on consecutive days) | https://registry.npmjs.org/astro | 9 Oct 2026 | verified |
| F63 | Astro React islands | `@astrojs/react` 7.0.1; no client directive = HTML with no JavaScript; `client:only="react"` renders only in the browser | https://docs.astro.build/en/reference/directives-reference/ | 9 Oct 2026 | verified |
| F64 | Tailwind 4 in Astro | Through the `@tailwindcss/vite` plugin in the Astro config; tailwindcss 4.3.3 | https://tailwindcss.com/docs/installation/framework-guides/astro | 9 Oct 2026 | verified |
| F65 | shadcn/ui in Astro | New project: `npx shadcn@latest init -t astro` (sets up Tailwind and the React integration) | https://ui.shadcn.com/docs/installation/astro | 9 Oct 2026 | verified |
| F66 | Astro routing | Default output `'static'`; a dynamic route needs `getStaticPaths()`, so `/o/<id>` is one static shell served by the API for every id | https://docs.astro.build/en/guides/routing/ | 9 Oct 2026 | verified |
| F67 | Googlebot and JavaScript | Pages wait in a render queue, then headless Chromium runs the JavaScript | https://developers.google.com/search/docs/crawling-indexing/javascript/javascript-seo-basics | 9 Oct 2026 | verified |
| F68 | AI crawlers and JavaScript | GPTBot, OAI-SearchBot, ClaudeBot and PerplexityBot did not render JavaScript (server-log study, 17 Dec 2024; no newer measurement found) | https://vercel.com/blog/the-rise-of-the-ai-crawler | 9 Oct 2026 | verified (2024 data) |
| F69 | Keeping pages out of Google | `noindex` as a meta tag or `X-Robots-Tag` header; the page must not be blocked in robots.txt or the rule is never seen | https://developers.google.com/search/docs/crawling-indexing/block-indexing | 9 Oct 2026 | verified |
| F70 | Consent Mode v2 | Four types (`ad_storage`, `ad_user_data`, `ad_personalization`, `analytics_storage`); the `default` command runs before any `config` or `event`; EEA, UK and Switzerland users need consent; a Google-certified CMP is required for publishers (AdSense, Ad Manager, AdMob), not for advertisers | https://developers.google.com/tag-platform/security/guides/consent , https://support.google.com/tagmanager/answer/13695607 , https://support.google.com/admanager/answer/13554116 | 9 Oct 2026 | verified |
| F71 | GA4 recommended events | `begin_checkout`, `purchase` (requires `transaction_id`), `generate_lead` | https://developers.google.com/analytics/devguides/collection/ga4/reference/events | 9 Oct 2026 | verified |
| F72 | Claude Code `/goal` | After each turn a small fast model judges the condition from the transcript (it runs no commands); up to 4,000 characters; restored on resume; works with `claude -p`; clears itself on met, impossible, or an error you must fix | https://code.claude.com/docs/en/goal | 9 Oct 2026 | verified |
| F73 | Claude Code auto mode | Start with `--permission-mode auto`; `defaultMode: "auto"` in a project's `.claude/settings.json` has no effect; deny rules block in every mode; from v2.1.283 auto is the built-in starting mode in the terminal | https://code.claude.com/docs/en/permission-modes | 9 Oct 2026 | verified |
| F74 | Claude Code Remote Control | `claude --remote-control "<name>"` (alias `--rc`) runs an interactive session you can also drive from claude.ai or the Claude app | https://code.claude.com/docs/en/cli-reference | 9 Oct 2026 | verified |
| F75 | Claude Code `--worktree` | Creates worktrees under `<repo>/.claude/worktrees/<name>`; this project uses sibling worktrees from `scripts/dev/lane.sh` instead, so each lane has its own root, `.lane` file and hooks | https://code.claude.com/docs/en/cli-reference | 9 Oct 2026 | verified |
| F39 | uv | 0.12.24; `uv sync --locked` exits with an error when the lock is stale | https://pypi.org/pypi/uv/json , https://docs.astral.sh/uv/concepts/projects/sync/ | 9 Oct 2026 | verified |
| F40 | Python base image | `python:3.13-slim-trixie` exists (3.13.16); pin by digest | https://raw.githubusercontent.com/docker-library/official-images/master/library/python | 9 Oct 2026 | verified |
| F41 | Node.js | 24.21.0 is the current LTS ("Krypton") | https://nodejs.org/dist/index.json | 9 Oct 2026 | verified |
| F42 | Front-end packages | react 19.3.0, tailwindcss 4.3.3 (vite 8.3.4 is now only Astro's internal bundler, F62) | https://registry.npmjs.org/vite/latest (and react, tailwindcss) | 9 Oct 2026 | verified |
| F43 | Local emulators | Mailpit v1.31.4; Firestore emulator image `gcr.io/google.com/cloudsdktool/google-cloud-cli:emulators` | https://github.com/axllent/mailpit/releases/latest , https://raw.githubusercontent.com/GoogleCloudPlatform/cloud-sdk-docker/master/README.md | 9 Oct 2026 | verified |
| F44 | gitleaks | v8.30.1 | https://github.com/gitleaks/gitleaks/releases/latest | 9 Oct 2026 | verified |
| F45 | ffmpeg with zscale | Debian builds ffmpeg with `--enable-libzimg`; `ffmpeg -filters` lists `zscale` and `tonemap` | https://salsa.debian.org/multimedia-team/ffmpeg/-/raw/debian/master/debian/rules | 8 Oct 2026 | verified |
| F48 | GitHub Actions cost | Free for public repositories on standard GitHub-hosted runners; larger runners always charged | https://docs.github.com/en/billing/concepts/product-billing/github-actions | 9 Oct 2026 | verified |
| F54 | Claude Code hooks | Exit code 2 blocks a PreToolUse call; Stop hooks get `stop_hook_active` and can return `{"decision":"block","reason":...}`; 8-continuation cap; `${CLAUDE_PROJECT_DIR}` in commands; default timeout 600 s | https://code.claude.com/docs/en/hooks | 9 Oct 2026 | verified |
| F55 | Claude Code permission rules | `Bash(git push *)`, `Read(./.env)`, `Edit(path)`; deny beats allow; path rules for `Write` are ignored, use `Edit(...)` | https://code.claude.com/docs/en/permissions | 9 Oct 2026 | verified |
| F56 | Subagent files | Frontmatter `name`, `description` required; `tools`, `model`, `effort` optional | https://code.claude.com/docs/en/sub-agents | 9 Oct 2026 | verified |
| F57 | Context7 MCP | Server URL `https://mcp.context7.com/mcp`; API key in the `Authorization: Bearer` header | https://github.com/upstash/context7 (README) | 9 Oct 2026 | verified |
| F76 | uv Linux tarball | `uv-x86_64-unknown-linux-gnu.tar.gz` for 0.12.24: SHA-256 `b4dfaef47d491a7296981f8374a4595f55dbf84e8937c8ecd2983574d8bb3da6` (release asset `digest`) | https://api.github.com/repos/astral-sh/uv/releases/tags/0.12.24 | 9 Oct 2026 | verified |
| F77 | Node.js Linux tarball | `node-v24.21.0-linux-x64.tar.xz`: SHA-256 `fd8e59d5a511510f6a298afb548f18c7d2b1be404d8b4a27d94fbe49f56cb2d6`; gitleaks `gitleaks_8.30.1_linux_x64.tar.gz` digest matches STEP-01's `551f6fc8…f2470eb` | https://nodejs.org/dist/v24.21.0/SHASUMS256.txt , https://api.github.com/repos/gitleaks/gitleaks/releases/tags/v8.30.1 | 9 Oct 2026 | verified |
| F78 | `actions/checkout` pin | v7.0.1 (latest, 20 Jul 2026) = commit `3d3c42e5aac5ba805825da76410c181273ba90b1` | https://api.github.com/repos/actions/checkout/releases/latest | 9 Oct 2026 | verified |
| F79 | Repository rulesets API | `POST /repos/{owner}/{repo}/rulesets` (API version 2026-03-10); `enforcement` active; rules `pull_request` (`required_approving_review_count`, `allowed_merge_methods`…), `required_status_checks` (`context`, `strict_required_status_checks_policy` required), `non_fast_forward`, `deletion`; `conditions.ref_name.include` accepts `~DEFAULT_BRANCH` | https://docs.github.com/en/rest/repos/rules#create-a-repository-ruleset | 9 Oct 2026 | verified |
| F80 | Python packages (uv.lock) | pydantic 2.14.0, pydantic-settings 2.15.0, jinja2 3.1.6, google-genai 2.29.0, pillow 12.3.0, fastapi 0.143.0, uvicorn 0.54.0, google-cloud-firestore 2.34.1, google-cloud-storage 3.17.0, google-cloud-run 0.16.2, stripe 16.0.0, httpx 0.28.1, pytest 9.1.1, ruff 0.16.10, mypy 2.4.0, pre-commit 4.6.2, python-hcl2 8.1.4, grpcio 1.84.0; editor media: scenedetect-headless 0.7.1, opencv-python-headless 5.0.0.93, numpy 2.5.3, pillow-heif 1.8.0 (same versions the old kit pinned on 7 Oct 2026) | `uv add` output and uv.lock | 9 Oct 2026 | verified |
| F81 | pydantic-settings dotenv | Default `extra='forbid'` rejects unknown dotenv entries (set `extra='ignore'`); init kwarg `_env_file=None` disables the dotenv read; `case_sensitive` defaults to False; `env_ignore_empty` (default False) treats `KEY=` as unset, for dotenv values too (our test); precedence init kwarg > env > dotenv > default | https://github.com/pydantic/pydantic-settings/blob/main/docs/index.md (Context7) | 9 Oct 2026 | verified |
| F82 | gitleaks CLI | `gitleaks git [repo]` scans history; `--pre-commit --staged` scans the staged diff; `--redact`, `--no-banner`, `--timeout <s>`; exit 1 on a leak | `gitleaks git --help` (v8.30.1, local) | 9 Oct 2026 | verified |
| F83 | uv build backend, flat layout | `[tool.uv.build-backend]` `module-root = ""` with `module-name` puts the package at the project root instead of `src/` | https://github.com/astral-sh/uv/blob/main/docs/concepts/build-backend.md (Context7); `uv sync` builds it | 9 Oct 2026 | verified |
| F84 | PySceneDetect packaging | From 0.7 `scenedetect` requires `opencv-python` (GUI build, needs libGL); servers and containers install `scenedetect-headless`, which requires `opencv-python-headless`; both provide the same module and must not be installed together (mixing corrupts `cv2`) | https://github.com/breakthrough/pyscenedetect/blob/main/packaging/package-info.rst , website/pages/faq.md (Context7); `importlib.metadata.requires` on 0.7.1 | 9 Oct 2026 | verified |
| F85 | Type information of media packages | mypy 2.4.0 strict: `cv2` (opencv-python-headless 5.0.0.93), `numpy` 2.5.3 and `pillow_heif` 1.8.0 are typed; `scenedetect` 0.7.1 has no stubs or py.typed (`import-untyped`) | scratch import under `make types` | 9 Oct 2026 | measured |
| F86 | Cloud Logging fields in JSON stdout | `severity` becomes the entry severity (LogSeverity names; Python's DEBUG, INFO, WARNING, ERROR, CRITICAL are among them); `time` as an RFC 3339 string sets the timestamp; `message` is the display text; other fields stay in `jsonPayload` | https://docs.cloud.google.com/logging/docs/agent/logging/configuration#special-fields (updated 8 Oct 2026), https://docs.cloud.google.com/run/docs/logging (updated 7 Oct 2026) | 9 Oct 2026 | verified |
| F200 | Editor base image digest | `python:3.13-slim-trixie` multi-arch index `sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f` (updated 9 Oct 2026); its amd64 image is 43 MB compressed | https://hub.docker.com/v2/repositories/library/python/tags/3.13-slim-trixie | 10 Oct 2026 | verified |
| F201 | CI ffmpeg has zscale | Ubuntu noble's ffmpeg is built with `--enable-libzimg` (debian/rules line 74), so the ubuntu-24.04 runner's `ffmpeg` has `zscale` | https://git.launchpad.net/ubuntu/+source/ffmpeg/plain/debian/rules?h=ubuntu/noble-updates | 10 Oct 2026 | verified |
| F202 | OpenCV float Lab | `cvtColor` on 32-bit float images expects 0..1 input; Lab L comes out 0..100 | https://docs.opencv.org/5.0/main_modules/imgproc_color_conversions.html (Context7 /websites/opencv_5_0) | 10 Oct 2026 | verified |
| F203 | PySceneDetect API | `detect(video_path, detector)` returns `(start, end)` FrameTimecode pairs; `AdaptiveDetector(min_scene_len=...)` accepts `"0.6s"`; other defaults: adaptive_threshold 3.0, window_width 2, min_content_val 15.0 | https://github.com/breakthrough/pyscenedetect/blob/main/docs/api/detectors.rst (Context7 /breakthrough/pyscenedetect) | 10 Oct 2026 | verified |
| F204 | Hard cut detection on the fixtures | AdaptiveDetector finds the 90 s fixture's cut at 45 s within 0.1 s on the 1080x1920 proxy | tests/integration/editor/test_measure.py | 10 Oct 2026 | measured |
| F205 | uv image digest | `ghcr.io/astral-sh/uv:0.12.24` index `sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a` (the uv this repo pins, F39) | https://ghcr.io/v2/astral-sh/uv/manifests/0.12.24 | 10 Oct 2026 | verified |
| F206 | ffmpeg filters the editor uses | Documented in ffmpeg-filters: zscale (npl), tonemap (desat), lut3d (interp=tetrahedral), loudnorm (print_format, measured_I, linear), alimiter (level), atempo, ebur128, blackdetect (pix_th), freezedetect, boxblur, zoompan, overlay, anullsrc, apad, atrim, afade, aresample, setpts, concat, eq, split. Arguments are the kit's, byte-identical (phase B review). A single quote, colon or backslash in a quoted filter argument needs escaping, so LUT paths are refused when they hold one | https://ffmpeg.org/ffmpeg-filters.html | 10 Oct 2026 | verified |

## Product and craft

| ID | Fact | Value | Source | Accessed | Status |
|---|---|---|---|---|---|
| F53 | Baseline run (old kit, Agent SDK, Sonnet) | 5.7 min, $0.95, about 20 requests, 1.64M cache-read and 0.13M cache-write tokens | `runs/creamiopusday-2c99.jsonl` on Kevin's Mac | 7 Oct 2026 | measured |
| F58 | Instagram Reel length | Reels over 3 minutes are not recommended to new audiences; publishing API accepts 3 s to 15 min | https://about.instagram.com/features/reels , https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media | 8 Oct 2026 | verified |
| F59 | Speech cut rules | Gaps ≥400 ms "usually the cleanest"; 150–400 ms "usable with a visual check"; pad 30–200 ms; 30 ms audio fades | https://github.com/browser-use/video-use/blob/main/SKILL.md | 9 Oct 2026 | verified |
| F60 | Card fees in Spain (later, paid orders) | 1.5% + €0.25 per standard EEA card | https://stripe.com/es/pricing | 8 Oct 2026 | verified |

## Assumptions (not facts; each has the test that settles it)

| ID | Assumption | Used for | Settled by | Step |
|---|---|---|---|---|
| A1 | A cloud edit takes about 10 min on 4 vCPU | Job timeout, cost | Read `duration` of the first 10 cloud runs | 8–9 |
| A2 | 40 phone clips fit in 16 GiB with 1080p proxies made one file at a time | Job memory | Peak memory of a real 40-file run | 8 |
| A3 | Our own loop matches the old kit's quality at ≤ $1.20 per Reel | Switching engines | The A/B in step 4 | 4 |
| A4 | Gemini transcription handles Spain Spanish with stutters and retakes | Talking styles | Stutter test in step 5 | 5 |
| A5 | About 17 Firestore writes per order | Free-quota headroom | Count writes in the emulator for one order | 7 |
| A6 | iPhone Safari sends gallery photos as JPEG through a file input, so HEIC is not in the allowed types | Upload types | Upload a gallery photo from an iPhone and read its content type | 6 |
