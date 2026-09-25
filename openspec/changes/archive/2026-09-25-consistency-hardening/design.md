## Context

- **Live EV state.** `start_ev_manual_charge` (`backend/api/routers/ev.py`) reads SoC via `get_ha_sensor_float` and the plug via `get_ha_entity_state` + `resolve_plug_state`. When the plug is `unavailable`/`unknown`, `resolve_plug_state` returns the *last known* plug reading, so a start can be accepted for a charger that is currently unreachable. `_check_ev_manual_charge_end` (`executor/engine.py`) reads through the executor's `HAClient.get_state_value`, treats non-numeric SoC as unknown, and ignores unreachable plug states. The two paths use different HA clients: the module-level `backend.core.ha_client` in the API, and the executor's own `HAClient` instance.
- **Manual-charge status.** The executor owns `_ev_manual_charge` (in memory, under `_lock`) and mirrors it into `data/ev_multi_day_state.json` through `_persist_ev_manual_charge`. The charger list builder reads only the file copy. The API and the executor run in the same process, and `get_executor_instance()` returns `None` when no executor exists.
- **Slot duration.** `store_plan` writes `planned_water_heating_kwh` / `planned_ev_charging_kwh` as `kw * 0.25`. `schedule.py` divides planned and observed kWh by a hardcoded `duration_hours = 0.25`. `slot_plans` has no end column. `slot_observations` already has `slot_end`. Both `store_plan` callers pass the planner's schedule frame, which always carries `end_time` (`planner/output/formatter.py` requires it). `get_executions_range` has no callers.

## Goals / Non-Goals

**Goals:**
- One function decides what "SoC" and "plugged in" mean for the manual-charge start and end paths.
- `manual_charge` in the charger API reflects what the executor is actually doing.
- Planned and observed history is correct at any slot length.

**Non-Goals:**
- Changing the charger list's plug display. It keeps showing the last known plug state with `unreachable: true`, which is the intended dashboard behavior (ev-missed-goal-recovery).
- Changing how the planner or executor pick slot resolution.
- Backfilling `slot_end` for existing `slot_plans` rows.

## Decisions

### D1. Reader shape: pure interpretation + a thin async reader taking a state getter
New module `backend/core/ev_live_state.py`:

- `EVPlugState = Literal["plugged", "unplugged", "unknown"]`
- `@dataclass(frozen=True) EVLiveState(soc_percent: float | None, plug: EVPlugState)`
- `interpret_ev_live_state(charger_id, raw_soc, raw_plug, *, has_soc_sensor, has_plug_sensor, plugged_in_states) -> EVLiveState`: pure, no I/O.
  - SoC: `None` when there is no sensor, the raw value is missing or unreachable, or it is non-numeric; otherwise `float`.
  - Plug: no plug sensor → `"plugged"` (same assumption the planner makes). Missing raw value or `is_unreachable_state` → `"unknown"`. Otherwise `is_ev_plugged_in` decides between `"plugged"` and `"unplugged"`, and the valid reading is passed to `remember_plug_state` so the dashboard's last-known fallback stays fed.
- `async read_ev_live_state(charger_id, get_state, *, soc_sensor, plug_sensor, plugged_in_states) -> EVLiveState`, where `get_state: Callable[[str], Awaitable[str | None]]` returns a raw HA state string. A read that raises is logged at warning level and treated as a missing value, which makes the result `unknown`.

The API passes an adapter over `get_ha_entity_state` (returning `state.get("state")`). The executor passes `self.ha_client.get_state_value`.

*Alternative considered:* one shared HA client for both callers. Rejected because it merges two client lifecycles (per-event-loop sessions vs. the executor's own client), which is a much larger change than the drift being fixed.

### D2. Unknown-state policy stays with the callers
- **Start:** plug `"unplugged"` → "The car is not connected". Plug `"unknown"` → new error "The car's plug state is unknown (charger unreachable)". SoC `None` → existing "The car's SoC is unknown". `set_ev_manual_charge` gets `plug_state: EVPlugState` in place of `plugged_in: bool`, so the executor owns every rejection message.
- **End:** end only on SoC ≥ target, or plug `"unplugged"`. `"unknown"` never ends a charge. The 24 h timeout still applies.

### D3. `manual_charge` source: executor first, file as fallback
`get_ev_chargers` calls `get_executor_instance()` once per request. When an executor exists, each charger's `manual_charge` comes from `executor.get_ev_manual_charge_status()` (mapped to the same public shape as `_manual_charge_view`: `target_soc`, `current_a`, `started_at`; `expires_at` is not added to the response). When no executor exists, the current file read is used unchanged. The goal fields still come from the file.

*Alternative considered:* keep the file and add a consistency test. Rejected because a test cannot catch a runtime write failure (for example a persist error after the in-memory set).

### D4. `slot_plans.slot_end`
- Model: `slot_end: Mapped[str | None]`, nullable.
- Alembic migration adds the column in the same idempotent inspector style as `e9f1a2b3c4d5`, with `down_revision` = current head.
- `store_plan`: `slot_end` from `row["end_time"]` (or `slot_end`), normalized to local ISO exactly like `slot_start`. `duration_h = (end - start) / 3600 s`. If the end is missing or not after the start, the row is logged and `duration_h` falls back to 0.25 while `slot_end` is stored as NULL. The upsert updates `slot_end` too.
- `get_plans_range` returns `slot_end`.
- `schedule.py`: one helper `_slot_duration_hours(slot_start, slot_end) -> float`, returning the real duration, or 0.25 when `slot_end` is NULL, unparseable or non-positive. Used for both `planned_map` and `obs_map`.

### D5. Delete `get_executions_range`
It has no callers in code, tests or frontend. Deleting it is safer than fixing an unused copy of the history logic.

## Risks / Trade-offs

- **[Risk]** A charger with a flaky plug sensor now refuses manual starts while it is unreachable → Mitigation: the error message says why. The dashboard already shows the charger as unreachable.
- **[Risk]** When the executor exists but is not running its loop, the API shows in-memory state, not the file → Acceptable: memory is restored from the file at executor init, and the executor is the only writer.
- **[Risk]** Mixed old (NULL) and new rows in `slot_plans` on an install that changed resolution in the past → Mitigation: NULL means 15 min, which is exactly today's behavior. New rows are correct from the first plan after upgrade.

## Migration Plan

The Alembic migration runs on startup (existing mechanism). Rollback: the downgrade drops the column, and the old code ignores it anyway.

## Open Questions

None.
