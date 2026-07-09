# AGENTS.md - Darkstar Energy Manager

---

## Core Philosophy

- **Production-grade only**. No shortcuts, no quick fixes. Clean, maintainable, robust implementations.
- **NEVER ASSUME**. Verify everything. If uncertain, ask the user.
- **Respond concisely**. No unsolicited code, no lengthy explanations unless asked.

---

## Environment

- **Python**: 3.12 (see `.python-version`)
- **Package manager**: `uv` (virtual env in `.venv/`)
- **Frontend**: React + Vite, managed with `pnpm`

## Commands

| Task | Command |
|------|---------|
| Install dependencies | `uv pip install -r requirements.txt` |
| Run dev environment | `pnpm run dev` |
| Run single test | `uv run python -m pytest tests/test_file.py::test_name -v` |
| Run all checks | `./scripts/lint.sh` |

---

## Project Structure

```
backend/            - FastAPI API, Strategy Engine, Executor
frontend/           - React + Vite UI
planner/            - MPC scheduling logic (Kepler MILP solver)
ml/                 - Aurora ML pipeline (train.py, forward.py)
config.yaml         - Local configuration (environment-specific, never commit)
config.default.yaml - Shipped template with defaults
```

---

## UI Design System

All UI changes must follow the design system:

- **Guidelines**: `docs/design-system/AI_GUIDELINES.md`
- **Live preview**: `/design-system` route
- **SSOT for tokens**: `frontend/src/index.css`

---

## Boundaries

### ⚠️ Ask First

- Modifying files in `docs/` directory
- Database schema changes
- Adding new dependencies
- Major architectural changes
- Staging or committing git changes

### 🚫 Never

- Commit runtime data: `*.db`, `schedule.json`, `data/scheduler_status.json`
- Commit `config.yaml` — defaults go in `config.default.yaml`
- Commit secrets or API keys
- Modify `docs/RELEASE_NOTES.md` unless explicitly instructed
- Push git changes unless explicitly instructed

---

## Git & Commits

**Format**: Conventional commits with multi-`-m` flags for detail:

```bash
git commit -m "feat(executor): migrate to async aiohttp HTTP client" \
  -m "- Replace sync requests with async aiohttp for HA API calls" \
  -m "- Add 5-second timeout to prevent executor freezing" \
  -m "- Implement exponential backoff retry for transient errors" \
  -m "Fixes critical issue where executor froze when inverter became unresponsive."
```

---

## Troubleshooting

### AI Extension UI Desync

If a command completes but the UI still shows "Running":

- **Cause**: Multi-line strings inside `-m` quotes confuse the terminal parser
- **Prevention**: Always use single-line `-m` strings
- **Fix**: `pkill -9 -f "shellIntegration-bash"`
