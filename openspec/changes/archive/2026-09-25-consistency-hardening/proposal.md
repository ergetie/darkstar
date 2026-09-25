## Why

Three places in the code read or record the same facts in two different ways that happen to agree today but can silently drift apart:

- The manual-charge start API and the executor's end check read an EV's SoC and plug state separately, each handling unavailable values its own way.
- `GET /api/ev/chargers` reports `manual_charge` from the persisted state file, not from the executor that actually runs the charge.
- Planned kWh history assumes 15-minute slots (`* 0.25` / `/ 0.25`), even though slot length is configurable (`resolution_minutes`: 15, 30 or 60).

This change removes each duplication so every fact has one source.

## What Changes

- Add one shared live EV state reader that returns a charger's SoC and a three-way plug state (`plugged` / `unplugged` / `unknown`). The manual-charge start API and the executor's per-tick end check both use it.
- **Behavior change**: starting a manual charge is rejected when the plug state cannot be read (unavailable, unknown, or read error). Today the start API falls back to the last known plug reading. An already running manual charge still keeps going when a reading is unknown.
- `GET /api/ev/chargers` reads `manual_charge` from the executor when it is running, and falls back to the state file only when no executor instance exists.
- Add a nullable `slot_end` column to `slot_plans` (Alembic migration). `store_plan` records each slot's real end and converts planned water/EV kW to kWh with the real duration.
- The schedule history API converts planned and observed kWh back to kW using each row's stored duration (`slot_plans.slot_end`, `slot_observations.slot_end`), falling back to 15 minutes only for rows without a `slot_end`.
- Remove the unused `LearningStore.get_executions_range()`, which carries further hardcoded 15-minute assumptions and has no callers.
- Remove the three processed items from `docs/BACKLOG.md`.

## Capabilities

### New Capabilities
- `ev-live-state`: One reader for a charger's live SoC and plug state, with an explicit `unknown` plug result.

### Modified Capabilities
- `ev-manual-charge`: Start is rejected when the plug state is unknown. Manual-charge status in the charger API comes from the executor.
- `chart-planned-actual-display`: `slot_plans` stores each slot's end. Planned and observed history convert kWh to kW using the real slot duration.

## Impact

- **Code**: `backend/core/` (new reader module), `backend/api/routers/ev.py`, `executor/engine.py`, `backend/learning/store.py`, `backend/learning/models.py`, `backend/api/routers/schedule.py`.
- **Database**: one additive, nullable column (`slot_plans.slot_end`) via Alembic. Existing rows keep NULL and are read as 15-minute slots, exactly as today.
- **API**: `POST /api/ev/chargers/{id}/manual-charge` returns 400 "plug state unknown" when the charger is unreachable. No response shape changes.
- **Dependencies**: none.
