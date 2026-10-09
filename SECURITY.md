# Security

## You found a leaked key

If you see an API key, token or password in this repository, its history, an issue or a pull request:

1. Do not use it, copy it or post it anywhere else.
2. Report it privately through GitHub: **Security → Report a vulnerability** on this repository.
   Say where you saw it (file and commit, or link); do not paste the key itself. If that button is
   not there yet, open an issue titled "Security contact request" with no details, and the
   maintainer will reply with a private channel.

The maintainer revokes and replaces the key first, then removes it. A key that reached GitHub is
treated as compromised even after it is deleted from history.

## Other vulnerabilities

Use the same private report. Please give the steps to reproduce and what an attacker gains.

## How keys are kept out

- Keys live only in `.env` on the laptop (never committed) and in Secret Manager in the cloud.
- `gitleaks` runs before every commit and again in CI.
