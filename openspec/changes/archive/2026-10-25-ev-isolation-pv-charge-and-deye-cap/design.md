## Context

`Controller._follow_plan` picks a mode intent, then the shared min-SoC guard may turn `self_consumption`/`export` into `idle`, then charge values are computed. Profiles map mode intents to entity writes; templates `{{charge_value}}` and `{{max_charge}}` come from the decision.

Profile idle behavior (read from `profiles/*.yaml`): Deye idle = Zero Export To CT, grid charging off, `max_discharge_current` 15, `max_charge_current {{max_charge}}`. Fronius idle = Block Discharging. Sungrow idle = self-consumption mode, `max_discharge_power` 10 W, `max_charge {{max_charge}}`. `generic` = CONFIGURE_ME. PV charging stays possible in idle on Deye (user confirmed on hardware), Fronius and Sungrow.

## Decisions

**D1. PV-charge branch honours isolation.** Inside `elif slot.charge_kw > 0`, `mode_intent = "idle"` if `ev_isolating` else `"self_consumption"`; `plan_state.enter(None, None)` in both cases; set `note = EV_ISOLATION_REASON` for idle. Alternative (move the `ev_isolating` branch above PV charge) rejected: it would also bypass the grid-charge branch ordering and change the unchanged-by-design charge path. Grid-charge branch stays first: Deye does not discharge in grid-charge mode (user confirmed). Export branch stays: it needs `discharge_kw > 0`, which isolation zeroes, so it cannot co-occur. `ev_isolating` already requires `discharge_kw == 0`.

**D2. Guard composition.** The min-SoC guard only rewrites `self_consumption`/`export`. An isolated PV-charge slot is already `idle`, so the guard does not alter it or its note; the latch still updates from live SoC.

**D3. Reason note.** New constant `EV_ISOLATION_REASON` next to `HOLD_MARGIN_REASON`, appended by the existing `if note:` path. Also applied to the existing isolation `idle` branch (L271-278) so one reason covers every isolated idle; this branch currently has no note. Charge values for these idle decisions are computed as before and are not used by the idle actions that write them (`max_charge` on Deye and Sungrow).

**D4. Max charge unless export planned.** After `charge_value` is computed, extend the existing fallback override: if `mode_intent == "self_consumption"` and (`charge_value <= 0` or `slot.export_kw <= 0`), set `charge_value = max_charge`, `write_charge = True`. With `export_kw > 0` the planned value from `_calculate_charge_limit` stays, preserving the intentional "cap charging to enable export" behavior. Generic: any profile using `{{charge_value}}` in `self_consumption` benefits; Fronius and Sungrow do not use it there (Sungrow `self_consumption` (L150) and `idle` (L164) use `{{max_charge}}`).

**D5. Interplay checked.**
- `charge` mode keeps `_calculate_charge_limit` values (grid charge with `grid_charge_kw` None or positive reaches the `charge` branch; legacy `grid_charge_planned` at L237-241 is evaluated before and unchanged). Explicit `grid_charge_kw == 0` with `export_kw == 0` is the case that now gets max charge.
- Min-charge clamp (`min_a`/`min_w`) applies only inside `_calculate_charge_limit`; the max path bypasses it, as the existing fallback already does.
- Write deadband (`executor/actions.py` ~L834) applies to `{{charge_value}}` writes with load balancing on. Switching planned -> max is usually beyond one step; sub-step differences are skipped, which is harmless. No change.
- Battery load-balancer cap (`_apply_battery_cap`) acts on `charge` mode only; unaffected.

## Risks / Trade-offs

- With max charge and no planned export, the battery may absorb more PV than planned, so SoC can run ahead of the plan. Accepted by the user: stored PV beats exported PV, and the planner re-plans on SoC deviation.
- Residuals accepted: Deye idle can still discharge up to 15 A, Sungrow idle up to 10 W, into the EV. Not changed here.
- Existing tests that pin the old cap are limited to export-planned slots (`test_pv_surplus_uses_planned_charge_limit` has `export_kw=1.0`); verify by running the executor suite.

## Open Questions

None blocking.
