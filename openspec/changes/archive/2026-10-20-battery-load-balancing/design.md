# Design

## Context

- The balancer tick (`LoadBalancer.tick`) takes an ordered list of `EVBalancerInput | ShedLoadInput` that `_run_load_balancer` (`executor/engine.py`) builds from `give_way_order`. It runs a restore pass in reverse list order, then a top-down give-way pass with a running `pool_headroom`. Chargers fold their relief into the pool right away. Shed loads mark their phases in `pending_relief_phases` so entries below them hold for one tick.
- In the engine, the tick runs (`_run_load_balancer`, about line 1986) after `make_decision(...)` and before `self.dispatcher.execute(decision)` (about line 2160). So a cap on the decision lands in the same tick.
- How battery charge power is set today: `Controller._calculate_charge_limit` turns `slot.charge_kw` into `charge_value`. In `control_unit` "W" (Fronius, Sungrow) that is watts, rounded to `round_step_w` / `grid_charge_round_step_w` and clamped to `[min_charge_w, max_charge_w]`. In "A" (Deye, generic) it is DC battery amps through `ControllerConfig.nominal_voltage_v` (battery voltage, 48 V by default), rounded to `round_step_a` and clamped to `[min_charge_a, max_charge_a]`. Profiles map `{{charge_value}}` to `max_charge_current` (Deye/generic/Sungrow) or `grid_charge_power` (Fronius) in their `charge` mode. Planned grid charging is `mode_intent == "charge"` (`_follow_plan`: `slot.charge_kw > 0 and grid_charge_planned`). Deye's `soc_target` now points at program 6 SoC (commit dd3d0557). It is a separate action and this change leaves it alone.
- There is no config for how many phases the inverter uses. This change assumes a 3-phase inverter.

## Goals / Non-Goals

**Goals:**
- Let the user rank battery grid charging inside the give-way order.
- Reduce only grid-sourced battery charging, within `[0, planned]`, through the existing `charge_value` path for every profile and control unit.
- Reuse the existing ramp, restore, stale and replan mechanics.

**Non-Goals:**
- Planner per-phase awareness (BACKLOG "[Planner] Per-Phase Load Awareness").
- Overload timing based on a time-current curve (BACKLOG "[Load Balancer] Proportional Overload Timing").
- Throttling battery discharge or export, or PV charging in `self_consumption`.
- 1-phase inverters (no inverter-phase setting is added).
- Per-phase asymmetric inverter output.
- Notifications for battery interventions.

## Decisions

**D1 – New kind `battery` with a fixed id.** `GiveWayOrderEntry(kind="battery", id="battery")`. Parsing accepts `"battery"` (any other id is normalised to `"battery"`, and duplicates are dropped with a warning). Alternative considered: a shed-style `loads[]` entry. Rejected, because the battery needs continuous reduction, not on/off.

**D2 – Fixed 3-phase inverter.** The battery entry always draws on phases `[1, 2, 3]`. There is no setting for this. 1-phase inverter support is out of scope (user decision).

**D3 – Reduction math (AC side).** For the battery entry, take `deficit_a = max(0, -min(pool_headroom[p] for p in phases))`. The power cut is `cut_w = deficit_a × V × 3`, where V is `load_balancing.nominal_voltage_v` (grid nominal). That drops each phase by about `deficit_a`. The cut is limited by what is actually reducible (D4). The new cap `cap_w = max(0, current_cap_w - cut_w)` is never above `planned_w`. The battery's relief (`cut_w / (3 × V)` per phase) is folded into `pool_headroom` like a charger's, so entries below see only the remaining deficit.

**D4 – Only grid-sourced charge.** The battery entry is active only while `decision.mode_intent == "charge"`. Otherwise it reports `idle` and makes no change. Reducible power is `grid_part_w = min(applied_cap_w, max(0, current_import_kw × 1000))`. If the battery itself is drawing less than that (measured from `input_sensors.battery_power`, when configured), the lower value wins. The executor reads `battery_power` each tick (after `battery_power_inverted`, positive = discharge) into `SystemState.current_battery_charge_kw`. So the balancer never "relieves" power the battery isn't taking from the grid, and PV charging stays (the inverter keeps charging from PV up to the cap). Alternative considered: always reduce `charge_value` fully. Rejected, because when PV covers the battery, that would cut solar charging and give no phase relief.

**D5 – Applied through `charge_value` in the profile's unit.** The engine converts `cap_w` into `decision.charge_value`. For "W", it rounds down to the profile step. For "A", it computes `cap_w / ControllerConfig.nominal_voltage_v` and rounds down to `round_step_a`. Rounding down keeps the cap at or below what was asked. If rounding drops a cap that itself fits the profile minimum below it (a minimum that is not a multiple of the step), the minimum is dispatched. If the cap is below the profile minimum (`min_charge_w` / `min_charge_a`; Deye has 10 A), the engine switches `decision.mode_intent` to `"idle"` for that tick. `idle` turns grid charging off on every shipped profile and blocks discharge, which matches a planned charge slot. The reason text says so, and the status reports the battery as `paused` with a zero cap. The controller's `plan_state` latch is not changed, so the next tick re-evaluates against the plan. No new profile entities or modes are added, so Deye program-6 SoC handling is unaffected.

**D6 – Restore/ramp.** Increases reuse the charger rules. There is no raise for `ramp_up_window_s` after a reduction. Each raise must pass `avg_ok(phases, step_a)` against `target_margin_percent`. The step is `increase_step_a` per phase, converted to watts (`step_a × V × 3`), one step per tick, so recovery from a deep cut is deliberately gradual (the D8 replan covers sustained shortfalls). Raises stop at `planned_w`. A battery held at zero ("paused") takes part in reverse-order restore: entries above it wait until it restores, and it resumes once its phases fit the minimum charge for `resume_confirm_s` (no refit back-off). Balancer state is `throttling` while the cap is below plan and `paused` while grid charging is held off.

**D7 – Stale phase sensor.** When a battery phase is stale, the battery does not raise, keeps its current cap, and is not cut further. Stale is already reported through the chargers' `stale_fallback`. Rationale: battery grid charging is planned and steady, and cutting it on bad data would hurt the plan for no measured reason. Confirmed by the user.

**D8 – Sustained-throttle replan.** `_track_balancer_throttling` treats the battery output like a charger, key `"battery"`. It counts as constrained while the cap is below `planned_w`, or paused, during a `charge` intent. It fires `_maybe_fire_balancer_replan("battery", now)` after `replan_after_throttled_s`, with the same rate limit.

**D9 – Self-heal default placement.** `heal_give_way_order(lb, charger_ids, battery_available)` keeps one valid `battery` entry and drops it (with a warning) when no battery is controllable. Controllable means `system.has_battery` is not false and an inverter profile is loaded with a `charge` mode. The frontend mirror checks only `has_battery !== false`, since every shipped profile (and the generic fallback) has a `charge` mode. When the entry is missing and a battery is available, it is **appended at the end** (below all shed loads). This is the safest default for existing users and was confirmed by the user. Everything that worked before still gives way first, and the battery only acts where the fuse would otherwise stay overloaded, which is the reported case. The frontend `healOrderForDisplay` mirrors this. Nothing is written to `config.yaml` by heal. The order is saved when the user saves settings, like other healed entries.

**D11 – No notifications.** Battery throttle and pause do not trigger `notify_interventions` notifications for now (user decision). Status and the replan still apply.

**D10 – Status surface.** `LoadBalancerStatus` gains `battery_output: BatteryBalancerOutput | None` (`planned_w`, `cap_w`, `state`, `reason`, `phases`). `get_load_balancer_status()` adds a `battery` object (additive field). The status card and compact view show a battery row with planned vs capped kW, following `docs/design-system/AI_GUIDELINES.md` tokens. The give-way editor renders the battery entry with a battery icon and label "House battery (grid charging)".

## Risks / Trade-offs

- [Import-based estimate is coarse] Other loads on the same phases share the import. Mitigation: the cut is capped by both the import and the battery's own draw, and later ticks correct it from measured currents.
- [Inverter reaction lag / write threshold] Deye has `write_threshold_a` 5 A DC (about 240 W) and inverter ramp time. Mitigation: rounding down plus the shed-style one-tick hold for entries below the battery after a battery cut, using `pending_relief_phases`, so lower entries don't over-react.
- [Idle on floor] Switching to `idle` instead of a small charge loses a little planned energy. The replan (D8) recovers it.
- [Planned value semantics] `charge_kw` includes the PV share. Capping it may also limit PV charging during the cap. This is accepted, since the cap is lifted as relief allows.
