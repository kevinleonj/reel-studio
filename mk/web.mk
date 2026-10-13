# Lane web owns this file (STEP-06 and 07).
#
#   make ci-web          (part of make ci) web/: npm ci, astro check + build, ESLint, the ESLint policy test
#   make test-emulator   Orders and Mailer contract suites against the Firestore emulator and Mailpit
#   make prerelease      Playwright (phone 390x844 and laptop 1280x800, axe) + Lighthouse budget
#   make stripe-laptop   test mode: find or create the price and the beta coupon, write .env
#   make stripe-listen   webhook secret into .env (never printed), then forward Stripe test events
#   make up / make down  the whole site on the laptop through compose.yaml (STEP-06 task 6)
#   make dispatch-real   the real editor on the host instead of compose's fake one (paid)
#
# The web build needs SITE_URL (canonical links, sitemap, robots.txt). Locally it comes from .env;
# CI has no .env, so it falls back to the laptop tier's address from .env.example.

.PHONY: ci-web test-emulator prerelease stripe-laptop stripe-listen up down dispatch-real

NPM := npm --prefix web
# hardcode-ok on the next line: the laptop tier's address, as in .env.example
CI_SITE_URL := http://localhost:8080

ci-web:
	$(NPM) ci
	SITE_URL=$${SITE_URL:-$(CI_SITE_URL)} $(NPM) run build
	$(NPM) run lint
	$(NPM) test

test-emulator:
	$(UV) python -m tests.contract.run_emulator

# Builds first (pretest:e2e), so the browsers always test the current source.
prerelease:
	$(NPM) ci
	SITE_URL=$${SITE_URL:-$(CI_SITE_URL)} $(NPM) run test:e2e
	$(NPM) run lighthouse

# What compose's x-website-settings gives the containers, as the laptop itself sees it: the
# host processes (reelctl, the real-editor dispatcher) reach Mailpit and the emulator on loopback.
LAPTOP_HOST := TIER=laptop SMTP_HOST=127.0.0.1 SMTP_PORT=1025 DATA_DIR=./data WEB_DIST=./web/dist \
  FIRESTORE_EMULATOR_HOST=127.0.0.1:8681

# The containers run as the host user, so ./data stays writable on Linux too (compose.yaml).
COMPOSE := HOST_UID=$$(id -u) HOST_GID=$$(id -g) docker compose

# `check` validates the settings inside the image by the app's own rules and names what is
# missing, never a value; --wait returns once the api is healthy, or shows why it is not.
up:
	@test -f .env || { echo "copy .env.example to .env first"; exit 1; }
	mkdir -p data
	$(COMPOSE) build
	$(COMPOSE) run --rm --no-deps api python -m reel_studio.api.main check
	$(COMPOSE) up --detach --wait || { $(COMPOSE) logs --tail 20 api dispatcher; \
	  echo "make up failed; make down stops what started"; exit 1; }
	@echo "Reel Studio on port 8080 of this machine (SITE_URL in .env); inbox on port 8025, this machine only"

down:
	$(COMPOSE) down

# STEP-07 task 9: the real editor (paid: Claude, at most the step's budget) instead of the fake.
# It runs on the host, where the editor extra and ffmpeg are, against compose's emulator, Mailpit
# and ./data; compose's own dispatcher is stopped first so only one takes the slots.
dispatch-real:
	$(COMPOSE) stop dispatcher
	$(LAPTOP_HOST) $(UV) python -m reel_studio.api.main dispatch-real

# STEP-07 tasks 8 and 9 without `stripe login` or a host install: both read STRIPE_SECRET_KEY
# (test mode only) from .env and never print it; the Stripe CLI runs as a pinned image (F322).
# stripe-laptop is safe to run again; stripe-listen stores the signing secret in .env, then
# forwards the two checkout events to the site until Ctrl-C (F313).
stripe-laptop:
	$(LAPTOP_HOST) $(UV) reelctl stripe-setup

stripe-listen:
	$(LAPTOP_HOST) $(UV) reelctl stripe-listen
