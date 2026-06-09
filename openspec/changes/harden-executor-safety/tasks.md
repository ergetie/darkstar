## 1. Remove dead min_soc_floor plumbing (#35)

- [ ] 1.1 Remove `min_soc_floor` param + attribute from `OverrideEvaluator.__init__` (`executor/override.py:115-122`)
- [ ] 1.2 Remove `min_soc_floor` from `evaluate_overrides` and its call site in `executor/engine.py:1207`
- [ ] 1.3 Grep the executor package to confirm no remaining reads of `min_soc_floor`; run the executor test suite to confirm no behavior change

## 2. Manual override stops writing to the inverter (#22)

- [ ] 2.1 Add a manual-override early-return guard in `_tick` mirroring the pause short-circuit (`executor/engine.py:1045-1056`): when `state.manual_override_active`, skip all inverter / EV / water writes
- [ ] 2.2 Keep state recording (execution history, slot observations) running on the manual-override path so the UI still reflects reality
- [ ] 2.3 Ensure the `MANUAL_OVERRIDE` path no longer reaches `_apply_override`'s idle-mode writes (`engine.py:1415`, `controller.py:119-189`)
- [ ] 2.4 Tests: manual override active → no inverter/EV/water writes; telemetry still recorded; manual override inactive → normal apply

## 3. EV control obeys manual override and force_stop (#23)

- [ ] 3.1 Gate `_control_ev_charger` (`executor/engine.py:1922-2036`) on override + quick-action state: under `MANUAL_OVERRIDE` skip EV writes; under `force_stop` command the charger off
- [ ] 3.2 Leave normal operation unchanged (follow `slot.ev_charger_plans` when no override/quick-action active)
- [ ] 3.3 Tests: `force_stop` stops a planned EV charge; manual override leaves EV switch untouched; normal slot follows the EV plan

## 4. Stale-schedule freshness check (#35)

- [ ] 4.1 Confirm the schedule's generation timestamp accessor in `_load_current_slot` (`executor/engine.py:1536-1597`)
- [ ] 4.2 Add optional config `executor.max_schedule_age_hours` (default 6) in the executor config + `config.default.yaml`
- [ ] 4.3 In the slot-load path, if `now − generated_at > max_schedule_age_hours`: emit a warning via the existing `record_forecast_error` / `SystemAlert` path and apply the slot-failure hold fallback (`override.py:145-160`)
- [ ] 4.4 Tests: stale schedule → alert + hold (no planned actions applied); fresh schedule → executes normally; unset config → default 6h used

## 5. Verify

- [ ] 5.1 Run the full executor test suite + the new tests; confirm green
- [ ] 5.2 Run `openspec validate harden-executor-safety --strict`
- [ ] 5.3 Manual smoke per design.md: simulate manual-override on, a `force_stop`, and a stale schedule; confirm no inverter writes / charger off / hold+alert respectively
