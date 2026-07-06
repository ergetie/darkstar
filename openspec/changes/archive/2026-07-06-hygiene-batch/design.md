## Context

Five S4 findings from `stabilization-review-2` (#1, #19, #20, #23, #25). Each is independently low-risk; batching them keeps one review + test surface. Current state per finding is documented with `file:line` evidence in `openspec/changes/stabilization-review-2/findings.md`. This design pins the few choices that have behavioral or migration nuance so implementation is mechanical.

## Goals / Non-Goals

**Goals:**
- Remove dead surface area (`schedule_planned` table/model, `inverter_ac_limit_kw` key) so it cannot be mistaken for live.
- Eliminate the cross-thread StaticPool hazard in the executor history engine.
- Make config truthful: one source for `charge_efficiency`; documented timestamp conventions.
- Add two defensive guards: reject implausible meter deltas; treat a schedule with no parseable `generated_at` as stale.
- Warn (not block) when an enabled device targets a mock/test entity id.

**Non-Goals:**
- No change to planning or dispatch behavior for any well-formed input.
- **Out of scope:** the preflight-replay limitation (#23.4) — historical replay through the full pipeline is a separate concern, explicitly deferred.
- Not archiving the 92k legacy `schedule_planned` rows anywhere; they have no analytical value (superseded by `slot_plans`).

## Decisions

### D1 — Drop `schedule_planned` via a forward Alembic migration
Remove the `SchedulePlanned` model (`backend/learning/models.py:159-165`, including its `date` index) and add a new Alembic revision whose `down_revision` chains from the current head that `op.drop_table("schedule_planned")` (upgrade) and recreates it (downgrade, for rollback parity). *Why a migration, not just a model deletion:* the table physically exists in production; deleting only the model leaves an orphan table. Rollback recreates the empty table (data is not restored — it is dead).

### D2 — Executor history engine: per-thread connections
Replace `poolclass=StaticPool` at `executor/history.py:85-100` with SQLAlchemy's default pooling for SQLite file URLs (`QueuePool`) while keeping `connect_args={"check_same_thread": False, "timeout": 30.0}` and the idempotent WAL pragma. *Why:* the tick thread and FastAPI workers currently share one connection's transaction state. Per-connection-per-thread removes the interleave hazard; WAL already allows concurrent readers/writer. *Alternative considered:* `NullPool` (open/close per use) — rejected as needless churn for a hot 60 s loop.

### D3 — `charge_efficiency` single source, behavior-preserving
`battery.charge_efficiency` becomes the single source of truth. The executor controller loader (`executor/config.py:527`) SHALL read `battery.charge_efficiency` when that key is present, falling back to its own value only when the battery section omits it. Remove the duplicate `executor.controller.charge_efficiency` key from `config.yaml` and `config.default.yaml`. *Behavior preservation:* this instance sets both to `0.92`; after the change the executor still resolves `0.92` from `battery.charge_efficiency`. A task explicitly verifies the executor's effective value is unchanged for the current config. *Alternative considered:* warn-on-divergence only (no re-plumb) — rejected because it leaves the trap in place; the finding asked for single-sourcing.

### D4 — Meter-delta plausibility ceiling
In `RecorderStateStore.get_delta` (`backend/recorder.py:88-176`), after scaling, reject a delta above a configurable ceiling `recorder.max_meter_delta_kwh` (default **50.0** kWh per 15-min slot ≈ 200 kW sustained, ~10× any residential service). Rejection mirrors the existing negative-delta path exactly: advance the stored baseline to `current_value`, log a warning, and return `(None, False)` — so the bad reading is dropped and the *next* tick computes a correct delta from the new baseline (no double-count). *Why reject, not clamp:* clamping invents an energy value; returning `None` lets the caller record the slot as unmeasured, which the energy-balance monitor already tolerates.

### D5 — Missing `generated_at` is stale
At `executor/engine.py:1582-1603`, when `generated_at` is absent or unparseable, set the stale warning and `return None, None` (hold / fall back) instead of falling through to slot lookup. *Why safe:* every planner-written schedule includes `meta.generated_at` (`store`/pipeline), so this only rejects malformed schedules; holding is the safe side. A task verifies no system-written fallback schedule lacks `generated_at` (else the executor would reject its own output).

### D6 — Mock-entity startup warning
At startup config/device validation, for each *enabled* device (EV, water heater, inverter), if its target entity id matches a mock/test pattern (case-insensitive substring `mock` or `test`, e.g. `input_boolean.ev_mockup`), log a single `WARNING` naming the device and entity. Non-blocking — the operator's mockup is a legitimate local setup (#25); this only removes the silent-phantom risk on a production instance.

## Risks / Trade-offs

- **[D2 pool change reintroduces locking under load]** → WAL + 30 s busy-timeout already handle concurrency; the 2026-01 locking era does not reproduce on current code (#19 evidence). Existing executor-history tests must stay green.
- **[D3 changes executor efficiency if configs currently differ]** → they are identical (0.92) here; the verification task gates this. On other installs where they differ, the operator's `battery.charge_efficiency` wins — which is the intended single source.
- **[D4 ceiling too low rejects a legitimate high-draw slot]** → default 50 kWh/slot is ~10× a 25 kW main service; configurable if a site needs more.
- **[D5 rejects a hand-crafted/test schedule with no `generated_at`]** → intended; such schedules are already anomalous, and the fault-injection pin is updated to assert the new behavior.

## Migration Plan

1. Ship code + Alembic revision together. `alembic upgrade head` drops `schedule_planned` on deploy.
2. Rollback: `alembic downgrade -1` recreates the empty table; the removed model/keys revert with the code. No data migration either direction (dead data).
3. No config migration required for operators — removed keys were dead (`inverter_ac_limit_kw`) or now redundant (`executor.controller.charge_efficiency`); a stale key left in a user's `config.yaml` is simply ignored.

## Open Questions

None blocking. Ceiling default (D4, 50 kWh) and mock-pattern matching (D6, substring `mock`/`test`) are the two tunable choices; both have safe defaults recorded above.
