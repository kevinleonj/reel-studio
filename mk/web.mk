# Lane web owns this file (STEP-06 and 07).
#
#   make ci-web          (part of make ci) web/: npm ci, astro check + build, ESLint, the ESLint policy test
#   make test-emulator   Orders and Mailer contract suites against the Firestore emulator and Mailpit
#   make prerelease      Playwright (phone 390x844 and laptop 1280x800, axe) + Lighthouse budget
#
# The web build needs SITE_URL (canonical links, sitemap, robots.txt). Locally it comes from .env;
# CI has no .env, so it falls back to the laptop tier's address from .env.example.

.PHONY: ci-web test-emulator prerelease

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
