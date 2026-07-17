# Tasks: keep-on-slot-flag

## 1. Planner — flag instead of fake power

- [x] 1.1 Add `ev_keep_on: dict[str, bool]` field (default `field(default_factory=dict)`) to `KeplerResultSlot` in `planner/solver/types.py` (~lines 160-190)
- [x] 1.2 Rewrite the mutation body of `_apply_keep_on_after_target` in `planner/pipeline.py` (~lines 238-293): set `slot.ev_keep_on[charger_id] = True` for eligible future slots; DELETE the `slot.ev_charger_results[charger_id] = max_kw` and `slot.ev_charge_kw = sum(...)` injections; keep the eligibility logic (target met, `keep_on_after_target` true, slot before ready-by) untouched
- [x] 1.3 In `planner/solver/adapter.py:kepler_result_to_dataframe` (~lines 545-616), emit an `ev_keep_on` column next to the existing `ev_chargers` column (line ~607)
- [x] 1.4 In `planner/output/formatter.py:dataframe_to_json_response`, pass `ev_keep_on` through to the JSON records, normalizing non-dict values to `{}` (same pattern as `ev_chargers` at lines ~177-180); omit or write `{}` for slots with no keep-on
- [x] 1.5 Rewrite `tests/planner/test_keep_on_after_target.py`: all 6 tests currently asserting `ev_charger_results["ev1"] == 11.0` / `ev_charge_kw == 11.0` in keep-on slots must instead assert `ev_charger_results` unchanged (0/absent), `ev_charge_kw == 0.0`, and `ev_keep_on == {"ev1": True}`
- [x] 1.6 Add a formatter/adapter test: a `KeplerResultSlot` with `ev_keep_on={"ev1": True}` round-trips to a JSON slot with `ev_keep_on: {"ev1": true}` and `ev_charging_kw: 0.0`; a slot without keep-on serializes with empty/absent `ev_keep_on`

## 2. Executor — flag-aware decisions

- [x] 2.1 Add `ev_keep_on: dict[str, bool]` field (default `field(default_factory=dict)`) to `SlotPlan` in `executor/override.py` (~lines 100-103)
- [x] 2.2 In `executor/engine.py:_parse_slot_plan` (~lines 1902-1919), parse `slot_data.get("ev_keep_on") or {}` into `SlotPlan.ev_keep_on`; the aggregate backward-compat fallback (lines 1916-1919) stays unchanged (old schedules encode keep-on as fake power, which still works through it)
- [x] 2.3 Add engine helper `_charger_should_be_on(slot, charger_id) -> bool` returning `slot.ev_charger_plans.get(charger_id, 0.0) > 0.1 or slot.ev_keep_on.get(charger_id, False)`
- [x] 2.4 Use the helper at the switch-close decision in `_control_ev_charger` (engine.py ~2958-2959) replacing the bare `charger_plan_kw > 0.1` check
- [x] 2.5 Use the helper in `_run_load_balancer` (engine.py ~2637-2645); when the charger is on solely via keep-on (plan kW ≤ 0.1), set `planner_target_a` to `charger_cfg.min_current_a` (the configured per-charger minimum — do NOT hardcode 6) instead of `None`
- [x] 2.6 Use the helper in `_run_ev_surplus_and_phase` (engine.py ~2526-2527); for keep-on-only slots use the power equivalent of `charger_cfg.min_current_a` as `target_power_kw` for phase-mode selection (use the existing `one_phase_min_kw`/`three_phase_min_kw` helpers from `executor/ev_surplus.py`)
- [x] 2.7 Extend the source-isolation trigger in `tick` (engine.py ~1340-1377): `scheduled_ev_charging` is true when planned kW > 0.1 OR any `ev_keep_on` flag is set on the current slot
- [x] 2.8 Extend the secondary isolation check in `executor/controller.py:202` (`_follow_plan`): treat any keep-on flag on the slot like `ev_charging_kw > 0.1` when forcing `idle` over `self_consumption` (SlotPlan is available to the controller — verify field access, do not read schedule JSON here)
- [x] 2.9 Append a keep-on note naming the affected charger ID(s) (e.g. `"EV keep-on active: ev1"`) to the tick reason text (engine.py ~1385-1420) when a charger is on solely via keep-on; no ExecutionRecord/DB changes
- [x] 2.10 Include `ev_keep_on` in `current_slot_plan` in `get_status` (engine.py ~440-475)

Also fixed two latent gaps surfaced while implementing the above (not separate
tasks, but required for 2.4-2.6 to actually work end to end): the isolation
slot-reconstruction in `tick` now preserves `ev_keep_on` (it previously reset
to `{}`, which would have silently broken 2.8's controller check), and
`_control_ev_charger_current`'s no-balancer-configured fallback path now also
targets `min_current_a` for keep-on-only slots (it previously recomputed from
`charger_plan_kw` directly, which resolves to `None` when keep-on is the only
signal).

`/opsx:verify` (2026-07-17) found and this session fixed two further issues:
- `_update_ev_surplus_and_phase_mode` (2.6's phase-mode site) had reimplemented
  the keep-on-only check inline instead of calling `_charger_should_be_on`
  (2.3's helper) — violating the "single shared predicate, cannot diverge"
  design intent (D3), even though behavior was currently equivalent. Now calls
  the helper directly.
- The keep-on reason-text marker (2.9) was only ever appended inside the
  `if ev_should_charge_block and self._has_battery:` branch, so a battery-less
  system (`system.has_battery: false`) would never surface it in
  `override_reason`/history badges even though the switch is still correctly
  held on. Extracted the reason-text construction into a pure
  `_build_ev_reason_note` static helper, called from both the isolating and
  non-isolating branches, so the keep-on marker is set regardless of battery
  presence — single implementation, no divergence risk between the two paths.
Both covered by new tests in `tests/executor/test_ev_keep_on.py`
(`TestPhaseModeUsesSharedShouldBeOnPredicate`, `TestEvReasonNoteBatteryless`).

## 3. Executor tests

- [x] 3.1 New test (extend `tests/e2e/test_ev_schedule_e2e.py` or `tests/executor/`): binary charger — `SlotPlan(ev_charger_plans={"ev1": 0.0}, ev_keep_on={"ev1": True})` → `_control_ev_charger` commands the switch ON
- [x] 3.2 New test: current-type charger in keep-on with 0 planned kW → load balancer input carries the charger's configured `min_current_a` as planner target (configure a non-default value like 8 in the test to prove it is not hardcoded) and the relay path is commanded
- [x] 3.3 New test: keep-on slot with 0 measured EV power → battery discharge is blocked by source isolation
- [x] 3.4 New test: slot without `ev_keep_on` key parses to empty flags and all decisions fall back to planned power only (backward compat)
- [x] 3.5 New test: `get_status().current_slot_plan.ev_keep_on` returns the flag dict
- [x] 3.6 Run the adjacent executor suites that share the modified code paths: `tests/executor/test_ev_isolation.py`, `test_executor_safety.py`, `test_ev_current_control.py`, `test_executor_engine.py`, `test_ev_surplus_engine.py`, `test_executor_history.py`, and `tests/ev/` (209 passed)

New tests live in `tests/executor/test_ev_keep_on.py` (9 tests).

## 4. Frontend — standby visuals

- [x] 4.1 Add `ev_keep_on?: Record<string, boolean>` to `ScheduleSlot` in `frontend/src/lib/types.ts` (~line 12); add the same field to the executor status `current_slot_plan` type in `frontend/src/pages/Executor.tsx` (that's where it's typed, not `api.ts`)
- [x] 4.2 `frontend/src/components/ChartCard.tsx`: render a thin fixed-height "EV standby" band at the chart bottom for slots where `ev_charging_kw ≤ 0.01` and `ev_keep_on` has any true value; own legend entry "EV standby" (own overlay toggle `evKeepOn`); tooltip text "Charger switch held on after target — car draws only what it needs"; slots with planned EV power keep normal bars
- [x] 4.3 `frontend/src/pages/Executor.tsx` (~line 1019): next-slot badge shows "🔌 EV standby" when `current_slot_plan.ev_charging_kw ≤ 0.1` and `current_slot_plan.ev_keep_on` has a true flag; plain "🔌 EV" when charging is genuinely planned (> 0.1)
- [x] 4.4 `frontend/src/pages/Executor.tsx` (~line 1085): history rows show "🔌 EV standby" when `record.ev_charging_kw` is 0 and `record.override_reason` contains the keep-on marker from task 2.9 (`EV_KEEP_ON_REASON_MARKER` shared constant, matching `engine.py`'s `EV_KEEP_ON_REASON_MARKER` literal)

## 5. Verification

- [x] 5.1 Full test suite green (`scripts/ci_local.sh`) — ruff, pyright, 1589 pytest, OpenAPI schema (85 paths), frontend eslint all clean
- [x] 5.2 Generated a real plan (actual `KeplerSolver` + `_apply_keep_on_after_target` + `kepler_result_to_dataframe` + `dataframe_to_json_response`, only HA I/O out of scope) with an EV at 100% SoC / `keep_on_after_target: true`: resulting slots have `ev_charging_kw: 0.0`, `ev_chargers: {}`, `ev_keep_on: {"ev1": true}`, and 0 phantom grid import
- [x] 5.3 Drove the real `ExecutorEngine._parse_slot_plan` + `_control_ev_charger` over a generated keep-on slot (dispatcher/ha_client mocked at the I/O boundary): switch commanded ON with `charging_kw=0.0`; `get_status().current_slot_plan.ev_keep_on` covered by `tests/executor/test_ev_keep_on.py::TestGetStatusExposesKeepOn`
- [x] 5.4 Visual check: verified via `tsc --noEmit`, `eslint`, `vitest` (183 passed), and a production `vite build` (no errors); logic for the standby band (own dataset/legend/tooltip) and both badges was code-reviewed against the existing bar/badge patterns. Live in-browser confirmation not performed this session (no keep-on slot was reachable — active EV goal never reached 100% SoC due to the separate quota bug logged in `docs/BACKLOG.md`); revisit once that's fixed and a real keep-on slot exists.
