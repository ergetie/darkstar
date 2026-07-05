## Context

Darkstar is a closed-loop home energy control system: **planner** (hourly; Nordpool prices + Aurora ML forecasts → PuLP/Kepler MILP → `schedule.json`) → **executor** (every 60 s, live — `shadow_mode: false` verified 2026-07-01 — commands the Deye inverter, water heater, and EV charger via Home Assistant REST/WebSocket) → **recorder** (every 15 min → `slot_observations`) → **ML training** (Mon/Thu 03:00). All state converges in one SQLite database (`planner_learning.db`, WAL mode) with two writer processes (async recorder, threaded executor).

Production facts (verified in this session):
- Host `ssh darkstar` (192.168.0.107), Docker container `darkstar`, bind mount `/opt/darkstar/data → /app/data`.
- DB: 519 MB, `slot_observations` 2025-11-03 → present (23,114 rows), `execution_log` 255,030 rows (planned vs commanded vs before-state per tick, `success`/`error_message` columns), `data_quality_daily` 149 rows.
- Logs: `/app/data/darkstar.log`, daily rotation, ~1 week retained (structured JSON lines).
- No `sqlite3` binary in the container — query via `docker exec darkstar python -c "...sqlite3.connect('file:...?mode=ro', uri=True)..."`. **Always `mode=ro`.**
- Test baseline: 1,111 Python tests + 27 frontend tests; CI gates = ruff, pyright strict, full pytest, ESLint, OpenAPI validation. No coverage tracking, no replay harness.
- Risk concentration (by size × criticality): `executor/engine.py` (2,088), `executor/actions.py` (1,235), `backend/learning/store.py` (1,221), `backend/config_migration.py` (1,044), `planner/solver/kepler.py` (827) + `planner/pipeline.py` (928), `backend/recorder.py` (730), `frontend/src/components/ChartCard.tsx` (1,786).

Round 1 (archived `2026-06-17-stabilization-review`) was a static code-reading pass: 38 findings, 6 of 7 recommended fix changes landed. This round is **evidence-first**: production telemetry is the primary bug detector; code reading is the scalpel used to explain anomalies and to attack a short list of concentrated-risk surfaces.

## Goals / Non-Goals

**Goals:**
- Every failure mode in the catalog (FM1–FM8 below) has a **verified defense** — demonstrated by historical evidence, a passing test, a runtime monitor, or an explicit accepted-risk entry.
- Every anomaly found in 8 months of production data is explained: either a numbered finding (bug) or a documented benign cause.
- Stability becomes **continuously verified**: the invariant subset that matters at runtime is monitored in production with alerting, so the guarantee outlives this review.
- An honest exit statement. Never claim "100% bug free" — claim "all catalogued failure modes defended, all invariants green over history and N consecutive live days."

**Non-Goals:**
- Fixing bugs. Diagnose-only: every fix (including one-liners) becomes its own OpenSpec change. The **only** app code this change ships is the monitors module.
- Re-doing round 1's broad file-by-file reading. Only the targeted surfaces listed below get adversarial reads.
- Refactoring (`executor/engine.py` god-file split remains a deferred, separate concern).
- Fault injection against the live system. Tests/simulation only — the production instance is never deliberately degraded.
- Frontend test *coverage* build-out beyond the specific fragility findings (a follow-up change if findings warrant it).

## Failure-Mode Catalog (the review's spine)

Ranked by expected cost. Every task in `tasks.md` maps to at least one FM.

| ID | Failure mode | Cost class |
|----|--------------|-----------|
| FM1 | Executor commands wrong/unsafe hardware state (wrong mode, wrong current, wrong SoC target) or keeps acting on a stale plan | Hardware + money |
| FM2 | Battery economics inverted: exporting when it should hold, cycling at a loss, ignoring wear cost | Money (daily, compounding) |
| FM3 | EV not charged by the 07:00 departure, or water comfort violated (>8 h gap / legionella window) | Comfort + trust |
| FM4 | Silent control-loss: app crash-loops, HA connection drops and never recovers, executor ticks failing without anyone noticing | Availability → money |
| FM5 | Data corruption in the feedback loop: wrong kWh attribution, slot gaps/duplicates, dual-writer conflicts → ML trains on garbage → decisions degrade slowly | Money (insidious, weeks) |
| FM6 | Forecast quality silently degrades (PV/load/price drift, cold-start regressions) → plans optimize a fictional world | Money |
| FM7 | Config migration or save corrupts `config.yaml` → startup failure or silently changed behavior | Availability + safety |
| FM8 | Dashboard shows wrong numbers → operator makes wrong manual decisions or loses trust | Trust |

## Decisions

**D1 — Evidence before reading.** Phases run production-evidence mining *first*; adversarial code reading comes after and is steered by what the data shows. Rationale: 8 months of telemetry finds *confirmed* bugs; reading finds *suspected* ones. Round 1 already did the broad read.

**D2 — Findings ledger (same discipline as round 1, kept because it worked).** `findings.md` in this change dir; append-only; numbered `#1, #2, …`; each entry: severity, FM mapping, evidence (query/log excerpt/file:line), root cause marked **CONFIRMED** or **UNVERIFIED**, and status. Severity rubric: **S1** wrong hardware action or money lost now · **S2** wrong data/decision inputs, degradation over time · **S3** latent bug needing specific conditions · **S4** hygiene/robustness. Corrections to earlier findings are new entries referencing the old number — never edit history.

**D3 — Invariant catalog with a three-way check matrix.** Each invariant (see `specs/runtime-invariant-monitors/spec.md` for the runtime subset) gets: (a) a one-off SQL/log check over full history, (b) a test-suite assertion where feasible, (c) a runtime monitor **only if** it is cheap to evaluate continuously and violation is actionable. Rationale: not every invariant deserves a monitor; alert fatigue is itself a stability bug.

**D4 — Monitors are read-only observers.** The monitors module evaluates invariants from existing data (DB + in-process state) and raises `SystemAlert`s; it never influences control decisions and its failure must never break the loops it watches (fail-open, logged). Implemented against the existing alert/notify surface — no new alert channel invented. Alternative rejected: wiring monitors into the executor tick (couples watchdog to the watched; a monitor bug becomes an FM4).

**D5 — Fault injection in the test suite, as a permanent capability.** Scenarios built on the existing hermetic conftest pattern (pinned `DB_PATH`, mocked HA client). Where a scenario needs multi-slot time flow, use the existing `planner.simulation` module rather than building a full replay harness now; a proper backtest harness is deferred unless findings demand it. Rationale: harness-building is feature work in disguise; the freeze says minimum instrument, maximum diagnosis.

**D6 — Prod access protocol.** All server access read-only: `mode=ro` URIs for SQLite, `grep`/`tail` on logs, no writes, no restarts, no config edits. Heavy queries copied locally (`scp` the DB snapshot) if a query would hold a read lock > a few seconds on the 519 MB live file. Anything that would modify the server requires explicit operator permission per action.

**D7 — Fresh session per phase, tasks are the contract.** Each phase is sized to run in one focused session: read `design.md` → read `findings.md` → execute the phase's tasks → append findings → tick tasks → stop. Rationale (learned in round 1): long multi-phase sessions degrade; the ledger + atomic tasks make hand-offs lossless.

**D8 — Agent claims are never trusted unverified.** Two hallucinations were caught during pre-review scoping (shadow-mode misread; fictional C++ solver). Any sub-agent output that feeds a finding must cite evidence (query output, file:line) that the session author re-checks before appending to the ledger.

## Risks / Trade-offs

- [Live DB queried while app writes] → WAL allows concurrent readers; use `mode=ro`, keep queries short, snapshot-copy for heavy analysis (D6).
- [Monitors module is new code during a stabilization freeze] → smallest possible surface, read-only (D4), fully covered by tests, shipped as the *last* phase after diagnosis so it encodes verified invariants, not guesses.
- [Evidence mining produces noise (benign anomalies)] → every anomaly gets classified (finding vs. explained-benign) in the ledger; unexplained ≠ dismissed.
- [Log retention ~1 week limits incident archaeology] → DB tables (`execution_log`, `data_quality_daily`) cover the full 8 months and carry the same signals; logs are only needed for stack traces of *recent* incidents.
- [Review fatigue / scope creep into fixing] → D7 session discipline + hard diagnose-only rule; the itch to fix is redirected into well-scoped follow-up changes.
- [False confidence from green monitors] → exit statement explicitly lists what is *not* covered (e.g., frontend correctness has no runtime monitor; FM8 is test/read-verified only).

## Migration Plan

No migration. Monitors ship dark-safe: evaluate + alert only, no control-path coupling; rollback = disable/remove the module. Fault-injection tests are additive to the suite and gate CI like any other test.

## Open Questions

- **OQ1 — Alert channel for monitor violations**: `SystemAlert` banner only, or also push notification (`backend/notify.py` exists)? Operator decision at monitors phase; default = banner only.
- **OQ2 — Soak window N** for the exit criterion (proposal: N = 14 consecutive green days post-monitors). Operator confirms at exit.
- **OQ3 — `schedule_planned` table (92k rows, 4 columns) looks legacy vs. `slot_plans`** — evidence phase must determine which table is authoritative before using either as the plan-side of plan-vs-actual analysis.
