## 1. Shared helper

- [x] 1.1 In `backend/core/ev_plug.py` add `DEFAULT_PLUG_UNREACHABLE_GRACE_MINUTES = 10`, outage tracking (`_unreachable_since`, `_last_outage_minutes`), `plug_unreachable_grace_minutes(charger_cfg)` parser (mirror `soc_stale_after_minutes`), and `resolve_plug_with_grace`; clear new state in `reset_plug_memory`
- [x] 1.2 Leave `resolve_plug_state` unchanged (planner, dashboard, ha_socket state resolution)
- [x] 1.3 Unit tests in `tests/backend/test_ev_plug_session.py` (or new file): within window, past window, never seen, last-known unplugged, window 0, outage minutes recorded on recovery

## 2. Config

- [x] 2.1 Add `plug_unreachable_grace_minutes: 10` with comment to the ev_chargers entry in `config.default.yaml` (never `config.yaml`)
- [x] 2.2 Parse it in `executor/config.py` (`EVChargerDeviceConfig`, near `missed_goal_grace_hours` ~1126)
- [x] 2.3 Add the number input to `frontend/src/pages/settings/components/EntityArrayEditor.tsx` beside "SoC Stale After" (type, default 10, min 0, max 240); confirm no migration is needed via config-migration tests

## 3. Wire the paths

- [x] 3.1 `interpret_ev_live_state`/`read_ev_live_state` take `plug_grace_minutes`; pass it from `executor/engine.py` (`_read_ev_plug_states`, ~1381 manual charge). Leave `backend/api/routers/ev.py` as is
- [x] 3.2 Planner (`ha_client.py`, `planner/pipeline.py`) untouched; existing missed-goal tests must stay green
- [x] 3.3 `backend/ha_socket.py` re-plans on reconnect only when the outage lasted at least the grace window
- [x] 3.4 Leave load balancer phase fail-safes and all other sensors untouched

## 4. Tests

- [x] 4.1 Executor: `_gate_ev_plan_on_plug_state` keeps the plan during a short outage and drops it after the window (extend `tests/executor/test_ev_plug_gating_and_reminder.py`)
- [x] 4.2 ha_socket: no re-plan on short reconnect; re-plan after a long outage; plug-state changes still re-plan (extend `tests/ev/test_ev_charger_unreachable.py`); mock `_trigger_ev_replan` and dispatchers so no real webhooks are called
- [x] 4.3 Run existing missed-goal replay tests to confirm the planner is unchanged
- [x] 4.4 Run `./scripts/lint.sh` and the touched test files with `UV_NO_SYNC=1`
