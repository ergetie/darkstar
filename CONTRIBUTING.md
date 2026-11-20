# Contributing to Darkstar

Thanks for helping improve Darkstar. This guide covers setting up a development environment, running the checks and what a good pull request looks like. Please also read the [Code of Conduct](CODE_OF_CONDUCT.md).

## Getting started

Requirements: Python 3.12 (see `.python-version`), [`uv`](https://docs.astral.sh/uv/), Node 22 and `pnpm` 10.

```bash
# Backend
uv venv
uv pip install -r requirements.txt -r requirements-dev.txt

# Frontend
cd frontend && pnpm install
```

Run the development environment from the repository root with `pnpm run dev`.

Dependencies are pinned in `requirements*.txt`, not in uv's lockfile. Always prefix ad-hoc `uv run ...` commands with `UV_NO_SYNC=1`, otherwise uv regenerates a meaningless `uv.lock` stub:

```bash
UV_NO_SYNC=1 uv run python -m pytest tests/path/to/test_file.py::test_name -v
```

Do not commit `config.yaml`, `secrets.yaml`, databases or any runtime data. Defaults belong in `config.default.yaml`.

## Running the checks

Run all checks (Ruff, Pyright, pytest, frontend format, lint, typecheck and tests) before opening a pull request:

```bash
./scripts/lint.sh
```

The frontend also has a browser smoke test that runs the built UI against the real backend with Home Assistant unavailable:

```bash
cd frontend && pnpm test:e2e
```

## Tests

Changes should include tests: a regression test for a bug fix and tests for new behavior. Backend tests live in `tests/`, frontend tests sit next to the code as `*.test.ts(x)`.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/) with a short single-line subject and optional extra `-m` lines for detail:

```bash
git commit -m "fix(executor): retry transient Home Assistant errors" \
  -m "- Add exponential backoff for 5xx responses"
```

Common types are `feat`, `fix`, `docs`, `refactor`, `test` and `chore`, with the affected area as scope.

## UI changes

Follow the design system in [`docs/design-system/AI_GUIDELINES.md`](docs/design-system/AI_GUIDELINES.md). Design tokens live in `frontend/src/index.css`.

## Contributing an inverter profile

Adding support for a new inverter means writing a YAML profile in `profiles/`. Follow [`docs/inverter-profiles/CREATING_INVERTER_PROFILES.md`](docs/inverter-profiles/CREATING_INVERTER_PROFILES.md) and validate it with:

```bash
UV_NO_SYNC=1 uv run python scripts/validate_profiles.py profiles/your_brand.yaml
```

New profiles start with `status: community`. A maintainer promotes a profile to `tested` after it has been verified on real hardware. You can also open an [inverter profile request](https://github.com/ergetie/darkstar/issues/new/choose) if you cannot write the profile yourself.

## Pull requests

- Keep each pull request focused on one change.
- Fill in the pull request template.
- Make sure `./scripts/lint.sh` passes.
- Reporting a security problem? Do not open a public issue; see [SECURITY.md](SECURITY.md).
