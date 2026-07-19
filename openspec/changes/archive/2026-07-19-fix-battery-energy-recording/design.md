## Context

`backend/recorder.py` already has a working, proven pattern for computing energy from cumulative meters: `calculate_energy_from_cumulative()` fetches a configured HA cumulative sensor, asks `RecorderStateStore.get_delta()` for the change since last reading (with meter-reset detection and time-proportional scaling already handled), and falls back to `power_kw * 0.25` only when the cumulative sensor is missing or its meter just reset. PV, load, and grid import/export (dual-meter case) all use this path today. Battery never has — `batt_charge_kwh`/`batt_discharge_kwh` are always `(battery_kw * 0.25)`, gated only by the sign of a single instantaneous `battery_power` reading.

The needed cumulative sensors are already configured on production (`input_sensors.total_battery_charge` / `total_battery_discharge`, pointing at `sensor.inverter_total_battery_charge` / `sensor.inverter_total_battery_discharge`) and are already health-checked (`backend/health.py`). They are two independent, monotonically-increasing counters — one accumulates only while charging, the other only while discharging — which is exactly the shape the grid `dual` meter type already handles (`total_grid_import` / `total_grid_export` as two independent cumulative sensors). No new plumbing is needed: `get_cumulative_kwh(key)` already resolves any `input_sensors` key by name.

## Goals / Non-Goals

**Goals:**
- Battery charge/discharge energy uses the cumulative sensors when configured, with the exact same delta/fallback/reset-detection semantics PV/load/grid already use.
- Installs that have not configured `total_battery_charge`/`total_battery_discharge` keep today's snapshot behavior unchanged (no regression).
- No schema or config changes; no changes to what the `energy_balance` monitor checks — only the accuracy of the values it reads.

**Non-Goals:**
- Not retroactively recomputing/backfilling historical `slot_observations` rows — past snapshot-derived values stay as-is.
- Not touching `backend/learning/backfill.py` — it doesn't compute battery energy today (SoC-only), so it's unaffected.
- Not changing the `battery_power_inverted` config flag's meaning — it continues to apply only to the snapshot fallback path, since the two cumulative counters are separately-signed by construction (charge-total vs. discharge-total) and have no "inversion" concept.
- Not changing the `energy_balance` monitor's thresholds — this change addresses the data feeding it, not the check itself.

## Decisions

**1. Mirror the existing dual-meter pattern, not the single-net-meter pattern.**
Battery charge/discharge is structurally identical to `grid_meter_type: dual` (two independent cumulative counters, each only counting one direction). Implement it the same way: one `calculate_energy_from_cumulative("total_battery_charge", ..., "battery_charge_total")` call and one `calculate_energy_from_cumulative("total_battery_discharge", ..., "battery_discharge_total")` call, each independently falling back to today's snapshot formula for its own side if its cumulative sensor is absent or reset.
Alternative considered: derive both values from a single net cumulative sensor (like the grid `net` meter type). Rejected — no such single battery sensor is configured or known to exist on Deye inverters; the two-sensor shape is what's actually available.

**2. New state-file keys: `battery_charge_total`, `battery_discharge_total`.**
Follows the existing naming convention (`pv_total`, `load_total`, `grid_import_total`, `grid_export_total`). First run after deploy has no prior state for these keys, so `get_delta()` returns `None` and that one slot falls back to the snapshot method — the same one-slot cold-start gap PV/load/grid had when cumulative tracking was first added for them. Self-resolving, no action needed.

**3. Fallback stays per-flow, not all-or-nothing.**
If `total_battery_charge` is configured but `total_battery_discharge` is not (or one meter resets), only that side falls back to snapshot for that slot; the other side still uses its cumulative delta. Matches how PV/load/grid already degrade independently.

**4. No feature flag.**
This is a strict accuracy improvement with an automatic, per-sensor fallback to current behavior — the same risk profile as the March 2026 change that added cumulative calculation for PV/load/grid, which shipped without a flag.

## Risks / Trade-offs

- **[Risk]** First slot after deploy has no baseline for the two new state keys → that slot's battery energy falls back to the snapshot method (same known gap it has today) → **Mitigation**: none needed, self-resolves next slot; matches precedent.
- **[Risk]** An install without `total_battery_charge`/`total_battery_discharge` configured sees no improvement → **Mitigation**: expected and acceptable; behavior for those installs is unchanged, not regressed.
- **[Risk]** Meter-reset or implausible-delta detection (`max_meter_delta_kwh`, default 50 kWh) could mask a real large battery event → **Mitigation**: reuses existing, already-tuned logic; battery capacity here is 27 kWh so a legitimate full-cycle delta in one slot is well under the ceiling.
- **[Trade-off]** Existing `slot_observations` rows with snapshot-derived battery values are not corrected → historical `energy_balance` analysis before this deploy still shows the old error pattern; only forward-looking data improves.

## Migration Plan

1. Ship the recorder change; no config or schema migration required (sensors are already configured, columns already exist).
2. First recorder cycle after deploy: cold-start fallback for battery (as noted above), then normal cumulative-delta operation from the second cycle onward.
3. Rollback: revert the recorder change; no data cleanup needed since the state-file keys are additive and harmless to leave in place.
4. Verification: watch `energy_balance` monitor status and the daily dropout-rate query (SoC-delta vs. recorded battery energy) used during investigation — expect the rate to drop from the current spike back toward (or below) the historical ~2-5%/month baseline.

## Open Questions

(none — investigation already confirmed sensor availability, config, and the exact code path to change)
