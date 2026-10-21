# Design: min-soc-floor-tracking

## Context

See proposal.md (Why). Verified current state:

- `executor/controller.py` `_hold_mode` latches idle at `target − SOC_TRACKING_MARGIN` and unlatches at `live >= target`. The controller has no access to `min_soc_percent`: `ControllerConfig` lacks it and `SystemState.min_soc_percent` is never populated by `_gather_system_state` (always the dataclass default 10).
- Profiles: `fronius` and `sungrow` write no SoC target in any mode, so `self_consumption` discharges to the inverter's own reserve. `deye` and `generic` write `{{soc_target}}` in every mode, which limits the damage there.
- `BatteryPlanState.enter` resets the latch whenever kind or target changes. Today a charge block with target 12 latches idle at 12, the next hold slot (target 12) resets and runs self-consumption down to 10, and the next charge slot charges again. This is the reported Charge → Self-consumption → Idle cycle.
- `planner/solver/kepler.py`: `soc[0] == initial_soc`, then `soc[t] >= min_soc_kwh − soc_violation[t]` for all states, with `MIN_SOC_PENALTY` 1000 SEK/kWh. The export-floor constraint also uses `min_soc_kwh` for non-export slots. Benchmark solves already lower `min_soc_kwh` to the recorded ends.
- `planner/output/soc_target.py`: hold targets are the unclamped entry SoC; discharge targets are `min_soc`; charge-block targets are clamped up to `min_soc`.
- The planner runs every 30 min (`every_minutes: 30`) plus event replans. The executor ticks every 60 s.

## Goals / Non-Goals

**Goals:**
- The executor's hold margin never discharges below `min_soc_percent`, on any profile.
- A small SoC deficit is refilled at a price-optimal time inside a bounded window.

**Non-Goals:**
- Tick-granularity overshoot in discharge or self-consumption slots (at most one 60 s tick of discharge past the floor). The planner now absorbs that drift without a forced top-up.
- Writing the Fronius minimum reserve, or adding a SoC-target entity to the Fronius or Sungrow profiles.
- Changing `MIN_SOC_PENALTY`, the s-index terminal target, Battery Top Up or manual overrides.

## Decisions

### D1: Hold floor = `max(target − 2, min(target, min_soc))`, strict lift
The latch engages at `live <= floor` and lifts at `live >= target and live > floor`.
- Above the minimum (target ≥ min + 2) this is exactly today's behaviour.
- Target between min and min + 2: the margin shrinks so the floor is min.
- Target at or below min: floor = target, so discharge is blocked immediately. The strict `> floor` lift prevents an idle/self-consumption flap when the target equals the floor; the block lifts only on a real gain (PV).
- Alternative rejected: clamping to `min_soc` alone (`max(target − 2, min_soc)`). For a recovery hold with target 11 and min 12 the floor would be 12, above the target, which contradicts the plan's own hold value and gains nothing, because idle is already the result.

### D2: `min_soc_percent` reaches the controller via `ControllerConfig`
Add `ControllerConfig.min_soc_percent`, read from `battery.min_soc_percent` in `load_executor_config`, so it reloads with `reload_config()`. The fallback is 10.0, the same as the planner adapter's fallback (`planner/solver/adapter.py`), so planner and executor agree when the key is absent. Alternative rejected: populating `SystemState.min_soc_percent`. That is runtime state gathered from HA, and the value is configuration. The unused field stays as is (out of scope).

### D3: Grid-charge latch unchanged (verified)
After the latch, the executor is in idle. Idle blocks load discharge on every profile (Fronius "Block Discharging", Sungrow 10 W, generic 0 A, and Deye 15 A plus `soc_target`). Drift below the target while latched is therefore standby or self-discharge only. Resuming charge at `target − 2` instead of earlier avoids repeated low-power top-ups, which are ~50–60 % efficient on Fronius. With D4, a drift below min no longer forces the planner to schedule an instant charge, so the cycle is broken. The latch reset in `BatteryPlanState.enter` is safe with D1: at `live >= target` both a fresh charge block and a fresh hold block at the minimum resolve to idle.

### D4: Per-state lower bound `floor_kwh[k]` in Kepler
Compute `floor_kwh[k]` for k = 0..T and use it in place of the scalar `min_soc_kwh` in the min-SoC constraint (all states, including terminal) and in the export-floor fallback term.
- State time: `slots[0].start_time + sum(slot_hours[:k])`.
- Recovery active when `min_soc_kwh − 5 % · capacity ≤ initial_soc < min_soc_kwh` and `benchmark is None`.
- If active: `floor_kwh[k] = initial_soc` for states earlier than `start + 6 h`, and `min_soc_kwh` otherwise. Terminal state T always uses `min_soc_kwh`, even when the horizon is shorter than 6 h.
- Otherwise: `floor_kwh[k] = min_soc_kwh` (benchmark keeps its own relaxed scalar).
- A step, not a linear ramp: the user's requirement is "back at min by the deadline, price decides when". A ramp would force partial charging in expensive early slots.

### D5: Constants, not settings
`MIN_SOC_RECOVERY_HOURS = 6.0` and `MIN_SOC_RECOVERY_MAX_DEFICIT_PERCENT = 5.0` go in `kepler.py`.
- 6 h covers the next intraday valley on 15-min spot prices (night trough, midday PV or solar dip) and the morning PV ramp. It is short enough that the battery does not sit below the minimum for most of a day.
- 5 points matches `SOC_MARGIN_PERCENT` in `backend/monitors.py`, the established "beyond normal BMS undershoot" threshold. Deeper deficits are anomalies, and the old immediate refill is the right answer for them.
- min_soc is a soft planning target and the BMS is the hard floor (`executor/override.py`), so a fixed, conservative window carries no safety risk that would justify a user knob. Adding a setting would mean UI, defaults and docs for a value nobody should need to tune.

### D6: Rolling anchor (stateless)
The window is anchored at each solve's first slot. A persisted "recovery started at" timestamp was rejected: it adds state to the planner and has to survive restarts. With a rolling anchor:
- The SoC cannot fall further, because the floor is the initial SoC.
- A fixed cheap slot stays inside the window as time approaches it, so it gets executed.
- Postponement is bounded by the 5-point hard bound.

### D7: Charge-block target not raised to min
In `soc_target.py`, the charge-block lower clamp becomes `min(min_soc, block_end_projection)` when a projection exists (the fallback paths keep `min_soc`). A charge block whose projected end is below min only exists during recovery. Raising it would make the executor charge beyond the plan in an expensive slot. Hold (entry SoC) and discharge (`min_soc`) targets are already consistent: with D1, a hold below min is idle, and a discharge slot at live ≤ min is idle.

## Risks / Trade-offs

- [Within the window, the solver may discharge PV-gained energy back down to the initial SoC. The executor stops discharge slots at `min_soc`, which leaves a small plan/actual gap] → It is rare (it costs wear and still needs a refill by the deadline). Any larger gap is caught by `soc_deviation` replans.
- [Rolling anchor during a monotonically falling price trend] → The floor prevents further decline, and the 5-point bound and BMS remain the backstop.
- [Fronius/Sungrow hold at min now imports from grid for house load where Auto would have used 2 % of battery] → Intended. It respects the user's configured minimum.
- [An existing planner spec scenario stated the lower bound was unchanged] → Modified in this change's `planner` delta.

## Migration Plan

No config or data migration. Rollback is a plain revert. The behaviour change is visible in execution history as fewer charge/self-consumption flips near the minimum.
