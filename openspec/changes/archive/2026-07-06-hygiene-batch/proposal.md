## Why

The `stabilization-review-2` ledger closed five S4 hygiene findings that carry no runtime emergency but quietly erode trust and invite future mistakes: dead data that could be mistaken for a plan source, a latent cross-thread DB connection hazard, config keys that lie to the operator, a schedule-freshness check that can be silently bypassed, an unbounded meter-delta that records physically-impossible spikes, and enabled devices that can point at mock entities on a production instance. Batching them keeps each low-risk fix in one reviewable change with one test surface.

## What Changes

- **#1 — Remove the dead `schedule_planned` table.** Drop the `SchedulePlanned` model, its index, and add an Alembic migration to drop the table. It has had no reader or writer since 2025-12-10; `slot_plans` is the authoritative plan record.
- **#19 — Executor history DB uses per-thread connections.** Replace `poolclass=StaticPool` (a single connection shared across the executor tick thread and FastAPI threadpool workers) with a normal per-thread pool. Removes a latent cross-thread transaction hazard.
- **#20 — Config truthfulness.** Delete the dead `executor.controller.inverter_ac_limit_kw` key (read by no code; the live limit is `system.inverter.max_ac_power_kw`). Single-source `charge_efficiency` so the planner and executor cannot silently diverge. Document the mixed DB timestamp conventions in code.
- **#23 — Two documented fault-injection gaps.** (a) A schedule missing `meta.generated_at` currently bypasses the staleness check — require `generated_at` and treat its absence as stale. (b) Add a plausibility ceiling to cumulative-meter deltas so a single impossible spike is rejected/clamped instead of recorded raw. *(The preflight-replay limitation #23.4 is explicitly out of scope.)*
- **#25 — Mock-entity startup warning.** On startup, warn (not block) when an *enabled* device (EV, water, inverter) targets a mock/test entity id (e.g. `input_boolean.ev_mockup`), so a production instance never silently plans capacity around a phantom device.

None of these change user-facing planning behavior; they remove dead surface area and add defensive guards.

## Capabilities

### New Capabilities
- `stabilization-hygiene`: Removal of dead data/config surface area and addition of defensive guards (meter-delta plausibility ceiling, schedule-freshness `generated_at` requirement, mock-entity startup warning, config single-sourcing) identified by stabilization-review-2 (#1, #20, #23, #25).

### Modified Capabilities
- `database-concurrency-safety`: The executor history SQLite engine SHALL use per-thread connections rather than a single shared connection, so concurrent access from the tick thread and API workers cannot interleave on one connection's transaction state (#19).

## Impact

- **Code**: `backend/learning/models.py` (drop model+index), new `alembic/versions/*` migration, `executor/history.py` (pool), `config.yaml` + `config.default.yaml` (dead key), `planner/solver/adapter.py` + `executor/config.py` (charge_efficiency single-source), `executor/engine.py` (`generated_at` freshness), the recorder/meter-delta path (`backend/recorder.py` / `executor` meter read), and device/config validation at startup (mock-entity warning).
- **Data**: `schedule_planned` table dropped (92,269 legacy rows from 2025-11→12; no value, superseded by `slot_plans`).
- **Behavior**: no change to planning or dispatch; a schedule with no `generated_at` is now treated as stale (safe side), and an impossible meter delta is rejected/clamped.
- **Tests**: existing fault-injection pins (`test_schedule_without_generated_at_bypasses_age_check`, `test_unit_outlier_spike_is_recorded_raw`) flip from documenting the gap to asserting the fix.
