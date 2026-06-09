## Context

The Kepler MILP solver enforces an export-floor SoC constraint so the battery is not sold down to the grid below a configured reserve (`export_floor_soc_percent`). The current constraint binds the **start-of-slot** SoC:

```python
# kepler.py ~453-457  (soc[t] is start-of-slot; soc[t+1] = soc[t] + charge - discharge/eff)
prob += soc[t] >= (
    export_floor_kwh * is_exporting[t]
    + min_soc_kwh * (1 - is_exporting[t])
    - export_floor_violation[t]
)
```

Because `soc[t]` is the SoC at the *start* of slot `t` and the battery discharges across the whole slot, a slot that starts at the floor ends below it. The solver therefore always permits one extra full-power export slot past the floor. Confirmed in a production schedule (66 kWh battery, 28% floor = 18.48 kWh, ~16.5 kW discharge): slot `22:30` started at 28.3% and exported 3.57 kWh, ending at 21.7% — ~6% below the floor — before export stopped at the next slot.

The slot energy balance is `soc[t+1] == soc[t] + charge[t]·η − discharge[t]/η`, so within an export slot SoC is monotonically decreasing and the slot minimum is `soc[t+1]`.

## Goals / Non-Goals

**Goals:**
- Ensure planned grid export never drives SoC below the export floor within a slot.
- Allow partial export in the boundary slot so the battery can land exactly on the floor (preserve export value; do not stop a whole slot early).
- Keep the change minimal and behaviour-preserving everywhere the floor was already respected.

**Non-Goals:**
- Changing self-consumption (non-export) discharge, which still respects only `min_soc`. The export floor is a grid-export gate, not a discharge floor.
- Introducing a new hard discharge floor or any new config field.
- Changing the soft-constraint design (binary + slack + penalty) or the `EXPORT_FLOOR_PENALTY` value.

## Decisions

**Decision: Bind the floor to end-of-slot SoC (`soc[t+1]`) instead of start-of-slot (`soc[t]`).**

```python
prob += soc[t + 1] >= (
    export_floor_kwh * is_exporting[t]
    + min_soc_kwh * (1 - is_exporting[t])
    - export_floor_violation[t]
)
```

Rationale: `soc[t+1]` is the SoC after that slot's export/discharge, i.e. the in-slot minimum. Requiring it to stay at/above the floor when exporting is exactly the property we want. Because export amount and `soc[t+1]` are linearly coupled through the energy balance, the solver will reduce `grid_export[t]` in the boundary slot until `soc[t+1]` lands on the floor — yielding partial export to exactly the floor rather than a one-slot overshoot or an early stop.

*Alternative considered — explicit "stop or reduce" post-processing:* detect the overshoot after solving and clamp export. Rejected: re-implements optimisation outside the solver, can produce sub-optimal/inconsistent plans, and is harder to test. The constraint reformulation is one symbol (`soc[t]` → `soc[t+1]`) and lets the LP do it correctly.

*Alternative considered — constrain both `soc[t]` and `soc[t+1]`:* redundant. Since SoC only falls within an export slot, `soc[t+1] ≥ floor` implies the start was also ≥ floor. End-of-slot alone is sufficient and stricter.

**Decision: Keep the soft formulation (binary `is_exporting[t]`, slack `export_floor_violation[t]`, penalty 1000 SEK/kWh).**

Rationale: preserves the existing escape hatch under extreme price spikes and avoids any risk of model infeasibility. Only the SoC term referenced by the constraint changes.

## Risks / Trade-offs

- [Existing tests assert the start-of-slot behaviour and may break] → Update `tests/planner/test_kepler_export_floor.py` to assert end-of-slot SoC stays ≥ floor while exporting; add the production scenario (66 kWh / 28% / 16.5 kW must stop at 28%, not ~22%).
- [Marginally less export value — the last fractional slot is throttled] → Intended and correct: that energy was being sold below the user's configured floor. Net effect is small and is the whole point of the floor.
- [`soc[t+1]` is defined for all `t in range(T)`] → Confirmed: the SoC array spans `range(T+1)`, so `soc[t+1]` is valid for every export slot including the last.

## Migration Plan

- Pure solver-logic change; no schema, config, or data migration. No state to migrate.
- Rollback: revert the single constraint line (`soc[t+1]` → `soc[t]`).

## Open Questions

None. The mechanism and fix are confirmed against production schedule data.
