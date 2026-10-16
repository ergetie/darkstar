## Context

- `executor/controller.py` `_follow_plan`: grid-charge slots select `charge` before any SoC check; `_calculate_charge_limit` only converts power. Then `round(live SoC) <= soc_target` selects `idle` (block discharge), else `self_consumption`. No hysteresis or dwell exists on this path (only for EV and the load balancer).
- `soc_target` (`planner/output/soc_target.py`): charge and export blocks use the projected SoC at block end for every slot; hold uses the entry SoC; discharge uses `min_soc`.
- Deye and generic profiles write the SoC target to the inverter in charge mode; Fronius and Sungrow do not.
- Immediate replans exist only for EV and load-balancer reasons (`ReplanReason`, `request_replan`). The executor's balancer limiter is `_executor_replan_allowed`.
- Each slot carries `soc_projected` (end-of-slot SoC); the previous slot's projection is the current slot's entry SoC.
- Production check (2026-10-15, read-only): PV forecasts are mostly too high (median day ratio ~0.88). Intraday correction from measured PV was rejected (see proposal).

## Goals / Non-Goals

**Goals:**
- No grid charging beyond the planned SoC on any inverter profile.
- No auto/block flipping around a hold target.
- A plan that no longer matches the battery is replaced within minutes.

**Non-Goals:**
- Fixing the PV over-forecast (backlog item).
- Intraday PV correction (evaluated and rejected).
- Changing how the chart records SoC.

## Decisions

**D1. Stop grid charging at target, per charge block.** In a slot that would select `charge`, select `idle` (hold) once `round(live SoC) ≥ soc_target`. Hold, not self-consumption, because the plan wanted the energy kept. Latch per block (consecutive grid-charge slots with the same target): resume only when SoC ≤ target − 2. Reset at block change.
- Alternative: rely on the inverter's own SoC target. Rejected: not all profiles support it.
- Solar-only charge slots are unchanged.

**D2. Hold margin of 2 points.** In a hold slot, stay in `self_consumption` while SoC > target − 2; block discharge once SoC ≤ target − 2; lift the block only when SoC ≥ target. State is per hold block and resets at block change.
- Why downward: it lets the battery cover a small PV shortfall at the current (often expensive) price, which is what users asked for, and bounds the extra use to 2 points per block. A symmetric margin above the target would never trigger in a PV shortfall and so would not stop the flipping.
- Alternative: minimum dwell time between mode switches. Rejected: still flips, just slower, and adds a timer with no SoC meaning.
- 2 points matches D1, keeping one rule for users to learn.

**D3. Deviation measured against the plan's trajectory.** Expected SoC now = linear interpolation between the slot's entry SoC and its `soc_projected`, by elapsed fraction of the slot. Deviation = |live SoC − expected|. Within the D2 margin the deviation stays ≤ 2, so the margin never triggers a replan on its own.

**D4. Replan trigger: deviation above the threshold for 5 minutes.** Time-based, not tick-based, so it is independent of `executor.interval_seconds` and covers SoC sensors that lag 1–2 minutes. At most one `soc_deviation` replan per 15 minutes, with its own limiter (separate from the balancer's). Skipped while SoC is unavailable, while a manual override or Battery Top Up is active, and in shadow mode only logged as "would replan".

**D5. One user setting.** `executor.soc_deviation_replan_percent` (default 10, 0 disables, 0–50), in `config.default.yaml`, `executor/config.py` and the settings UI (advanced). The 5-minute duration, 15-minute limit and 2-point margins are fixed constants: fewer knobs, documented in the setting's help text.

## Risks / Trade-offs

- [The hold margin uses up to 2 points of battery the plan wanted kept] → Bounded and visible in the log; the following replan accounts for it.
- [Laggy SoC sensors cause a small overshoot past the charge target] → At most one or two ticks of charging, far better than the rest of the block.
- [A PV shortfall in a hold slot shows up as grid import, not as SoC deviation] → Covered by D2 (battery covers the first 2 points, no flipping). Fixing the forecast itself is the backlog item.
- [Frequent replans on systems with a poor load forecast] → 5-minute persistence, 15-minute limit, setting 0 disables.
