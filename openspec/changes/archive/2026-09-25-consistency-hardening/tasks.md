## 1. Shared live EV state reader

- [x] 1.1 Create `backend/core/ev_live_state.py` with `EVPlugState`, frozen dataclass `EVLiveState`, pure `interpret_ev_live_state(...)` and async `read_ev_live_state(charger_id, get_state, *, soc_sensor, plug_sensor, plugged_in_states)` per design D1 (no plug sensor → `plugged`; unreachable/missing/read error → `unknown`; valid readings passed to `remember_plug_state`; non-numeric/unreachable SoC → None)
- [x] 1.2 Add `tests/backend/test_ev_live_state.py` covering every scenario in `specs/ev-live-state/spec.md` (normal, disconnected, unavailable plug with last-known plugged → `unknown`, non-numeric SoC, read error → `unknown` + warning, no plug sensor, no SoC sensor, last-known recorded)

## 2. Manual-charge start and end use the reader

- [x] 2.1 Change `set_ev_manual_charge` in `executor/engine.py` to take `plug_state: EVPlugState` instead of `plugged_in: bool`; reject `unplugged` with "The car is not connected" and `unknown` with "The car's plug state is unknown (charger unreachable)", keeping the existing check order and messages otherwise
- [x] 2.2 Replace the SoC/plug reads in `start_ev_manual_charge` (`backend/api/routers/ev.py`) with `read_ev_live_state`, using an adapter over `get_ha_entity_state` that returns the raw `state` string; pass `current_soc_percent` and `plug_state` to the executor
- [x] 2.3 Replace the SoC/plug reads in `_check_ev_manual_charge_end` with `read_ev_live_state` using `self.ha_client.get_state_value`; end only on SoC ≥ target or plug `unplugged`, and update the docstring
- [x] 2.4 Update `tests/executor/test_ev_manual_charge.py` and the fake executor in `tests/backend/test_ev_api.py` to the new `plug_state` argument; add tests: start rejected when plug `unavailable` despite last-known plugged; end check continues on plug `unavailable`; end check ends on `disconnected`; end check ends on SoC ≥ target

## 3. Charger API reads manual charge from the executor

- [x] 3.1 In `get_ev_chargers` (`backend/api/routers/ev.py`), fetch `get_executor_instance()` once per request; when present, take each charger's `manual_charge` from `executor.get_ev_manual_charge_status()` mapped through the same public shape as `_manual_charge_view` (`target_soc`, `current_a`, `started_at`); when absent, keep the current state-file read
- [x] 3.2 Add tests in `tests/backend/test_ev_api.py`: executor active + file empty → executor's charge shown; executor with no charge + stale file entry → no charge shown; no executor + file entry → file charge shown

## 4. slot_plans.slot_end and real slot duration

- [x] 4.1 Add nullable `slot_end: Mapped[str | None]` to `SlotPlan` in `backend/learning/models.py`
- [x] 4.2 Add an Alembic migration (idempotent inspector style as in `e9f1a2b3c4d5`, `down_revision` = current head) that adds `slot_plans.slot_end` as nullable String, with a downgrade that drops it
- [x] 4.3 In `store_plan` (`backend/learning/store.py`), derive `slot_end` from `end_time`/`slot_end` normalized to local ISO like `slot_start`, compute the duration in hours, convert `water_heating_kw` and `ev_charging_kw` with it, fall back to 0.25 h + NULL `slot_end` + warning when the end is missing or not after the start, and include `slot_end` in the upsert `set_`
- [x] 4.4 Add `SlotPlan.slot_end` to the `get_plans_range` select and `SlotObservation.slot_end` to the `get_observations_range` select
- [x] 4.5 In `backend/api/routers/schedule.py`, add `_slot_duration_hours(slot_start, slot_end) -> float` (real duration; 0.25 when `slot_end` is None, unparseable or non-positive) and use it in both `planned_map` and `obs_map`, replacing the hardcoded `duration_hours = 0.25`
- [x] 4.6 Delete the unused `LearningStore.get_executions_range`
- [x] 4.7 Extend `tests/ml/test_store_plan_mapping.py`: 15-min slot unchanged (2.75 kWh), 30-min slot (5.5 / 1.5 kWh), `slot_end` stored in local ISO, invalid end → NULL + 0.25 h fallback, upsert updates `slot_end`
- [x] 4.8 Add schedule API tests for `_slot_duration_hours` and the history maps: 60-min planned row → 11.0 kW, NULL `slot_end` → 15-min conversion, 30-min observation → `actual_water_kw` 3.0
- [x] 4.9 Add `tests/test_migration_slot_plans_slot_end.py` (pattern of `tests/test_migration_planned_ev_charging_kwh.py`) verifying the column is added to a populated `slot_plans`, existing rows keep NULL, and a second run is a no-op

## 5. Backlog and verification

- [x] 5.1 Remove the three items (Shared Live EV State Reader, Manual Charge Status Source in Charger API, Slot Duration in Planned kWh Storage) from `docs/BACKLOG.md`
- [x] 5.2 Run `./scripts/lint.sh` and the full test suite; all green
- [x] 5.3 Visually check the Dashboard (chart history with planned water/EV, EV card manual-charge status) and the EV charger page in the running dev app, since `ev.py` and `schedule.py` are shared API code
