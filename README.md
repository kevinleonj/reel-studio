# Reel Studio

Reel Studio turns up to 40 food clips into an Instagram Reel, one version with text and one clean,
using its own loop on the Claude Messages API and ffmpeg. It never posts to Instagram, adds music or
changes your input files.

Three ways to run it, one code base:

1. **Command line** with your own Claude API key: `reel make <folder> --style <style>`.
2. **Website on your laptop**, the same editor behind a small upload page.
3. **Hosted beta** on Google Cloud for invited friends.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) 0.12 or later, Python 3.13 (uv installs it), GNU make and
[gitleaks](https://github.com/gitleaks/gitleaks) 8.30 or later (`brew install gitleaks`).

```bash
git clone https://github.com/kevinleonj/reel-studio.git
cd reel-studio
make setup     # installs dependencies and the pre-commit hooks, creates .env from .env.example
make ci        # lint, types, tests and the repository guardrails
```

Making a Reel arrives with build step 03; until then `reel` only prints its usage.

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): components, ports and the three tiers
- [docs/DECISIONS.md](docs/DECISIONS.md): locked decisions
- [docs/build/README.md](docs/build/README.md): build steps and lanes
- [SECURITY.md](SECURITY.md): reporting a leaked key

## Licence

[MIT](LICENSE)
