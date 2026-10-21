# Proposal: min-soc-floor-tracking

## Why

A Fronius user (min SoC 12 %, 19.2 kWh) still sees Charge → Self-consumption → Idle every few minutes with SoC bouncing 10–12 % after battery-plan-tracking shipped. Two defects feed each other: the executor's 2-point hold margin lets self-consumption drain below `min_soc_percent` (Fronius "Auto" only stops at the inverter's own reserve), and Kepler then treats any SoC below the minimum as a 1000 SEK/kWh violation that must be refilled in the very first slot at any price, at ~50–60 % grid-charge efficiency on Fronius.

## What Changes

- Executor hold margin is bounded by `battery.min_soc_percent`: in a hold slot the controller never selects self-consumption at or below `max(target − 2, min(target, min_soc))`, so a hold at (or below) the minimum blocks discharge immediately. Applies to every inverter profile.
- The controller receives `battery.min_soc_percent` through `ControllerConfig` (reloaded with the rest of the executor config).
- The grid-charge latch is verified and left unchanged (it holds in idle, which never discharges by load).
- Kepler gets a below-minimum recovery window: when the initial SoC is below `min_soc` but not more than 5 points below it, the lower bound for SoC states before `start + 6 h` is the initial SoC instead of `min_soc`; from the deadline on, `min_soc` applies again. The solver chooses when to refill inside that window by price. Deeper deficits keep today's behaviour (immediate refill).
- Both values are fixed module constants, not settings.
- Charge-block `soc_target` is no longer raised above the plan's own block-end projection to `min_soc`, so executor charge targets match a partial recovery charge.

## Capabilities

### New Capabilities
- `min-soc-recovery`: how the planner recovers from an initial SoC below `battery.min_soc_percent` (recovery window, hard deficit bound, consistent charge targets).

### Modified Capabilities
- `battery-plan-tracking`: the hold-margin requirement gains the `min_soc_percent` lower bound and the no-flap rule for holds at or below the minimum.
- `planner`: the "Soft max-SoC bound with penalty" scenario "Lower bound behavior unchanged" now applies against the recovery-window lower bound.

## Impact

- `executor/controller.py` (`_hold_mode`), `executor/config.py` (`ControllerConfig.min_soc_percent`).
- `planner/solver/kepler.py` (per-state lower bound replaces scalar `min_soc_kwh` in the min-SoC and export-floor constraints).
- `planner/output/soc_target.py` (charge-block lower clamp).
- Tests: `tests/executor/test_battery_plan_tracking.py`, new `tests/planner/test_kepler_min_soc_recovery.py`, soc_target unit tests.
- No config, API, UI, schema or dependency changes.
