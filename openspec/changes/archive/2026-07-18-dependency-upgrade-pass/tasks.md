# Tasks: dependency-upgrade-pass

**BIG — multi-session change.** Every phase (## group) ends at a green-CI checkpoint: run `scripts/ci_local.sh`, report bumped versions (old → new) to the user, and STOP for the user's commit approval before the next phase (never commit without explicit permission). Each phase begins by re-running the gate to confirm a green baseline (other changes may have landed between sessions). If any single phase's fix set explodes (>~20 files), stop and report before continuing.

## 1. Phase A — dev toolchain

- [x] 1.1 Bump `ruff` to current in `requirements-dev.txt` (keep `==`); run `ruff check .` + `ruff format --check .`; apply the minimal fixes for new rules (or add targeted per-file ignores in `pyproject.toml` with a comment if a new rule is noise)
- [x] 1.2 Bump `pyright` to current (keep `==`); run the strict gate; fix flagged code minimally — this is the known pain point (the 1.1.408 hold exists because newer strict inference failed); count the affected files first and report if >~20
- [x] 1.3 Bump `pytest`, `pytest-asyncio`, `pytest-cov` to current and convert them to exact `==` pins; run the full suite; adjust for any pytest-asyncio API/config changes (`asyncio_mode` etc. in `pyproject.toml`)
- [x] 1.4 Convert remaining loose dev deps (`pandas-stubs`, `types-*`, `psutil`, `rich`) to current exact pins
- [x] 1.5 CHECKPOINT: `scripts/ci_local.sh` green → report versions → await commit approval

## 2. Phase B — runtime deps, group 1: web stack

- [x] 2.1 Bump `fastapi`, `starlette`, `uvicorn[standard]`, `httpx`, `aiohttp`, `websockets`, `python-socketio` to current within their existing major ceilings (lift a minor ceiling like `fastapi<0.136.0` only after reading its changelog for breaking notes); run the suite after the group; on failure, bisect by reverting one package at a time
- [x] 2.2 CHECKPOINT: gate green → report → await commit approval

## 3. Phase C — runtime deps, group 2: data/ML/DB

- [x] 3.1 Bump `pandas`, `scikit-learn`, `lightgbm`, `sqlalchemy` (within `<3.0.0`), `alembic` (within `<2.0.0`), `aiosqlite`; run the full suite PLUS a fixed-scenario planner run comparing plan properties before/after (existing solver tests); report any legitimate numeric drift instead of hiding it
- [x] 3.2 CHECKPOINT: gate green → report → await commit approval

## 4. Phase D — runtime deps, group 3: the rest + exact pinning

- [x] 4.1 Bump `pydantic`, `pyyaml`, `ruamel.yaml`, `pytz`, `python-dateutil`, `requests`, `nordpool`, `astral`, `open-meteo-solar-forecast`, `python-json-logger` to current; run the suite
- [x] 4.2 Convert ALL direct deps in `requirements.txt` to exact `==` pins at the versions just validated (direct deps only — no transitive freeze); preserve/update the explanatory comments, including the `pulp` ceiling comment (Phase F decides pulp)
- [x] 4.3 Delete the empty stub `uv.lock` (134 bytes, misleading — the lock-tool migration was consciously deferred, see design)
- [x] 4.4 CHECKPOINT: gate green → report → await commit approval

## 5. Phase E — Node 22 + pnpm 10 (toolchain parity)

- [x] 5.1 In all three Dockerfiles (`Dockerfile`, `darkstar/Dockerfile`, `darkstar-dev/Dockerfile`): replace apt `nodejs` with Node 22 from NodeSource's Debian repo; update the pnpm comments (the Node-22 blocker is now gone)
- [x] 5.2 Change `npm install -g pnpm@9` → `pnpm@10` in all Dockerfiles; update `.github/workflows/ci.yml`: `node-version: '20'` → `'22'` and the pnpm action-setup to 10
- [x] 5.3 Run `pnpm install` in `frontend/` with pnpm 10 to migrate `pnpm-lock.yaml`; run `pnpm test`, `pnpm build`, `pnpm lint`
- [x] 5.4 Verify a clean `docker build` of the main `Dockerfile` completes (frozen-lockfile install + frontend build inside the image)
- [x] 5.5 CHECKPOINT: gate green + Docker build green → report → await commit approval

## 6. Phase F — PuLP (conditional)

- [x] 6.1 Check PyPI: is `pulp` 4.0 released? If NO: bump within 3.x, keep the `<4.0.0` ceiling and its comment, skip 6.2-6.3
- [ ] 6.2 If 4.0 IS released: migrate every `prob.constraints[name]` dict access in `planner/solver/kepler.py` (the only file using the pattern, verified) to the 4.0 API; run the solver test suite and a fixed-scenario plan-parity check BEFORE touching the pin
- [ ] 6.3 Lift the ceiling to `<5.0.0` with an updated comment; run the full gate
- [x] 6.4 CHECKPOINT: gate green → report → await commit approval

## 7. Phase G — frontend minor/patch updates

- [x] 7.1 `pnpm update` in `frontend/` (semver-range-respecting minors/patches ONLY — no major bumps, they are out of scope); refresh the lockfile
- [x] 7.2 `pnpm test` (all 89+ tests), `pnpm build`, `pnpm lint` green
- [x] 7.3 Visual smoke check per the shared-code workflow rule: dashboard, executor page, settings tabs render correctly
- [x] 7.4 FINAL CHECKPOINT: full `scripts/ci_local.sh` + Docker build green → report the complete old→new version table → await commit approval
