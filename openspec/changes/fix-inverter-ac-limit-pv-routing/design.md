## Context

The Kepler MILP (`planner/solver/kepler.py:431-434`) caps inverter AC throughput with `discharge[t] <= max(0.0, inverter_ac_kwh - s.pv_kwh)`, algebraically `pv + discharge <= inverter_ac_kwh`. This assumes 100% of forecast PV crosses the AC inverter. That is only true for **AC-coupled** systems (battery on its own AC inverter). For **DC-coupled hybrid** inverters — the common home setup — PV charging the battery is a DC-to-DC path that never crosses the AC stage, so:

- The constraint is **over-restrictive**: when `pv > inverter_ac_kwh`, discharge is forced to 0 *and* the model implicitly assumes the surplus PV is lost or curtailed, even though it could legally charge the battery on the DC side. Plans that should route excess PV into the battery get suppressed (e.g. 8 kW AC inverter, 12 kWp array).
- It **under-constrains AC export**: nothing independently caps PV-to-AC (load + export), so the plan can assume grid export above the inverter's AC rating (stabilization-review finding #34). Real hardware clips this, so today's symptom is an over-optimistic export/cost estimate, not an unsafe command.

The constraint is also skipped entirely when `max_inverter_ac_kw` is unset (the default), so only configured users are affected today.

This is the same issue tracked in `docs/BACKLOG.md` ("[Planner] Inverter AC Limit Constraint Overcounts PV-to-Battery Path") and stabilization-review finding #34, now promoted to this change.

## Goals / Non-Goals

**Goals:**
- Model PV routing so the AC limit applies only to what actually crosses the AC inverter.
- Stop suppressing valid DC-coupled plans where surplus PV charges the battery.
- Independently bound PV-to-AC (load + export) by the inverter AC rating.
- Preserve existing behavior for AC-coupled systems and for the unset-limit default.

**Non-Goals:**
- No executor or recorder changes — planner-only.
- No change to ramping, wear, or efficiency modeling (these stay on total charge/discharge).
- No new forecasting behavior; PV forecast input is unchanged.
- Not solving DC-charge-power limits as a hardware spec database — at most a single optional config field.

## Decisions

### D1 — Split PV into routed flows
Introduce per-slot continuous variables `pv_to_battery[t] >= 0` and `pv_to_ac[t] >= 0` with the balance `pv_to_battery[t] + pv_to_ac[t] + curtailment[t] == s.pv_kwh`. The AC constraint becomes `pv_to_ac[t] + discharge[t] <= inverter_ac_kwh`. `pv_to_battery` is bounded by available battery charge headroom and the battery's charge-power limit.
*Alternative considered:* keep a single PV term and only add a separate export cap. Rejected — it fixes the under-constrained export but not the over-restrictive battery-charge suppression, which is the higher-value half.

### D2 — Battery charge sourcing
Battery charge in a slot is sourced from `pv_to_battery[t] + grid_import_to_battery[t]`. **Open:** whether to split the existing `charge[t]` variable or derive these as sub-flows that sum to it (see Open Questions). Leaning toward keeping `charge[t]` as the total and adding `pv_to_battery[t] <= charge[t]` plus the balance, to minimize blast radius on wear/ramping/efficiency constraints that already reference `charge[t]`.

### D3 — Topology awareness via config
Add an optional `inverter.topology` field: `dc_coupled` (default) | `ac_coupled`. For `ac_coupled`, battery charging crosses the AC side too, so the constraint reverts to including `pv_to_battery` (or equivalently the original `pv + discharge <= inverter_ac_kwh`). Default must be backward-compatible — see Migration.
*Alternative considered:* infer topology from other config. Rejected — too implicit; an explicit flag is auditable and matches how other inverter settings are configured.

### D4 — Keep the `max(0.0, …)` feasibility guard
The current formulation's value was avoiding an infeasible negative upper bound. The new constraint form (`pv_to_ac + discharge <= inverter_ac_kwh` with `pv_to_ac >= 0`) is naturally feasible (set `pv_to_ac = 0`), so the explicit `max(0.0, …)` clamp is no longer needed, but the equivalent feasibility property MUST be preserved and tested (the existing "PV exceeds limit → still feasible" scenarios must still pass).

## Risks / Trade-offs

- **More decision variables per slot → larger MILP, slower solve.** → Mitigation: these are continuous (not integer) variables with simple bounds; LP relaxation cost is low. Benchmark solve time on a representative 48 h horizon before/after.
- **Default-topology choice silently changes plans for existing configured users.** → Mitigation: default `dc_coupled` matches the physically-correct, less-restrictive model; document the behavior change in the change notes; AC-coupled users opt in.
- **Wear/ramping/efficiency constraints reference `charge[t]`.** → Mitigation: D2 keeps `charge[t]` as the total so those constraints are untouched; only the PV sub-flow and AC cap are new.
- **Regression surface in `tests/planner/`.** → Mitigation: the existing AC-limit scenarios become MODIFIED scenarios; add new DC- vs AC-coupled cases rather than rewriting wholesale.

## Migration Plan

1. Add `inverter.topology` with default `dc_coupled`; config migration sets it for configs that have `max_inverter_ac_kw` set but no topology (default `dc_coupled`).
2. Ship the new constraint behind the topology branch so `ac_coupled` reproduces the old math exactly (safe fallback).
3. Update `tests/planner/` AC-limit tests; add DC-coupled surplus-to-battery and AC-export-cap cases.
4. Rollback: revert to the single-term constraint; the new config field is inert if unread.

## Open Questions

- **OQ-A:** Split `charge[t]` vs. keep it as total with `pv_to_battery` as a sub-flow (D2). Decide during implementation against the wear/ramping constraint references.
- **OQ-B:** Does the DC charge path need its own power limit distinct from `max_inverter_ac_kw` (some hybrid inverters rate DC charge separately)? If yes, a second optional config field; if unknown, bound `pv_to_battery` by the existing battery charge-power limit only.
- **OQ-C:** Default topology — confirm `dc_coupled` is the right default for the installed base (most home hybrids are DC-coupled, but verify against known user configs before shipping).
