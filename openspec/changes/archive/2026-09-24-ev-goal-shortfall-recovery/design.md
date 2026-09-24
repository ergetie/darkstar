## Context

Incident 2026-09-24 (prod): goal 53% → 55% by 10:30, 1.2 kWh required. The planner put 4.8 kW into the 10:15 slot (1.2 kWh / 0.25 h). The go-e integration's entities went `unavailable` 10:14:50–10:21:45; the planner treated that as unplugged. Charging resumed 10:22 at 6 A (`floor(4800 / 690) = 6`, ~4.1 kW), delivered 0.5 kWh, and stopped at 10:30 with SoC still 53%.

Current code facts:
- Kepler slot duration is `end_time - start_time` for every slot including the in-progress one (`planner/solver/kepler.py:89-92`), so a replan at 10:22 still gives the 10:15 slot a full 0.25 h of EV capacity.
- Kepler forces `ev_energy = 0` for slots ending after `charger.deadline` (`kepler.py:437-439`).
- `resolve_next_ready_by` (`backend/core/ev_goal.py`) returns the next future occurrence, so once the deadline passes the goal moves to the next day (or to nothing, for one-off goals).
- `planned_kw_to_amps` (`executor/load_balancer.py:54`) floors the result.
- Charge-failure detection (`executor/engine.py` `_check_ev_charge_failure`) only notifies. It doesn't replan.
- A balancer-driven replan already exists via `scheduler_service.trigger_now()` with one-per-interval rate limiting (`engine.py` `_track_balancer_throttling`).

## Goals / Non-Goals

**Goals:**
- A goal missed while the car is plugged in keeps being pursued, cheaply, for a bounded grace window.
- The in-progress slot never promises energy that no longer fits in it.
- Delivered power is never below planned power because of rounding.
- A failed or restored charge promptly re-plans the remaining energy.
- "Unreachable charger" is a distinct state from "unplugged".

**Non-Goals:**
- Fixing the go-e Wi-Fi.
- Price caps or surplus-only rules for the grace window. The user chose "cheapest slots in the window".
- Multi-day quota semantics. The grace window applies only to same-goal, single-deadline recovery.

## Decisions

### D1: Grace window as an extended effective deadline
When `resolve` finds that the most recent past deadline for a goal is within `missed_goal_grace_hours` of `now`, the charger is plugged in (or unreachable, see D5), and SoC is still below target, the pipeline uses `effective_deadline = missed_deadline + grace` and `required_kwh` from live SoC as usual. The effective deadline is always capped at the next regular ready-by, whichever is earlier. The existing soft shortfall constraint and the deadline-zero rule then work unchanged against the new deadline.
- A goal saved (`last_updated`) after the deadline it would have missed gets no grace window. That deadline was never pursued.
- The missed deadline is computed as the previous occurrence of the goal's schedule (for `repeat: none`, `ready_by_date` + `ready_by`).
- Default `missed_goal_grace_hours: 4`, per charger in `ev_chargers[]`, with `0` disabling it. It's a config field, not a goal field, so it lives in `config.default.yaml`.
- *Alternative rejected:* a separate "recovery goal" object persisted in `ev_multi_day_state.json`. That adds state and sync paths. Deriving it on every plan is stateless and self-healing.

### D2: Partial first slot — EV-only capacity scaling
For the first slot, the pipeline passes `first_slot_remaining_h = (slot_end - now)`. Kepler uses `h_ev = min(h, first_slot_remaining_h)` in the EV energy bounds (the max bound always; the min-power bound too, so a semi-continuous "on" stays feasible). The kW reported for that slot becomes `ev_energy / h_ev`, so the executor commands the higher power.
- *Alternative rejected:* shrinking `h` for the whole first slot. That would also rescale PV, load and battery energy for the slot, a much wider change with forecasting side effects.

### D3: Ceil amps
`planned_kw_to_amps` becomes `ceil(planned_kw * 1000 / (230 * phases) - 1e-9)`, clamped to `[min, max]`, still returning `None` below `min`. The epsilon keeps exact multiples, such as 11.04 kW giving 16 A, from rounding up. The load balancer still caps against the fuse limits, so safety is unchanged.

### D4: Failure/recovery → replan
When failure detection first fires in an EV period, and when actual power first exceeds 0.1 kW after a fired failure, the executor calls `scheduler_service.trigger_now()`. These replans use their own 5-minute cooldown, independent of the balancer replan rate limit (one per planner interval). A recovery that lands inside the cooldown stays pending and fires on the first charging tick after the cooldown ends, so the replan that matters most is deferred, never dropped.
- *Alternative rejected:* sharing the balancer rate limit. With a 60-minute interval it drops the recovery replan that follows a failure a few minutes later — exactly the replan that moves the remaining energy to higher power. Storms are already bounded: at most one failure and one recovery replan per commanded period.

### D5: Unreachable state
`ha_socket` and the executor classify plug and switch states of `unavailable`/`unknown` as `unreachable`, a third state beside plugged and unplugged. For planning, an unreachable charger keeps its last known plug state for the grace logic and for the plan, and doesn't trigger an unplug replan. On its return, a plug-in replan fires as today. The EV API and the dashboard card show "Charger unreachable".
- *Alternative rejected:* keeping "unavailable = unplugged". Today that removed the plan mid-slot and lost the goal context.

## Risks / Trade-offs

- [Grace charging continues after the user expected it to stop] → it's bounded by `missed_goal_grace_hours`, stops on unplug, and `0` disables it.
- [Ceil amps exceed the planned power by up to 0.69 kW on 3 phases] → the balancer still enforces the fuse limits. Planned energy is slightly overshot, which is preferable to a shortfall.
- [Unreachable for a long time while the car actually left] → the unplug is detected when the charger comes back. The grace window bounds how long a stale plan can run, and nothing is commanded while it's unreachable anyway.
- [Replan storm on a flapping charger] → at most one failure and one recovery replan per commanded period, plus a 5-minute cooldown between them.

## Migration Plan

Additive config field with a default. No DB changes. Rollback: set `missed_goal_grace_hours: 0` or revert the code.

## Open Questions

None. The grace window and cost rule were confirmed by the user on 2026-09-24.
