## Context

This is the third of four EV changes that came out of the 2026-09-25 EV system rundown. Both earlier changes have landed and this design is rebased onto them:

- `ev-planning-model` (36f36a67): removed `MultiDayPlanner`/per-day quotas in favour of Kepler deferral tiers, derived charger power (`backend/core/ev_power.py`), a global `system.grid.nominal_voltage_v`, and `planned_by_day`.
- `ev-goal-lifecycle-feedback` (782a7afc): one replan helper `scheduler_service.request_replan` (+ `spawn_background`), planner run coalescing, `plan_pending`, assumed-plugged planning for unplugged chargers (from the live or persisted SoC), executor plug gating, and `last_planned_at` = wall-clock goal read time.

Current state (verified in code on 2026-09-26):

- **Energy endpoints** (`backend/api/routers/energy.py`) sum `slot_observations` per period.
  - Import cost is `Σ import_kwh × import_price_sek_kwh`.
  - Export revenue is `Σ export_kwh × export_price_sek_kwh`. `export_price_sek_kwh` is pure Nordpool spot.
  - `ev_charging_kwh` is summed and returned, but never costed.
  - The Grid & Financial card is in `frontend/src/components/CommandDomains.tsx`, around lines 320-360.
- **The recorder** (`backend/recorder.py:483-608`) already computes a per-charger dict, `ev_charger_energy` ("Task 8.1"). It is returned in the observation record, but nothing persists it. `slot_observations` has only the aggregate `ev_charging_kwh`.
- **SoC reads:**
  - `ha_client.py:548-567` sets SoC to `None` on a failed read, but logs "defaulting to 0%".
  - `_calculate_required_kwh` (`planner/pipeline.py:223-268`) then uses `target/100 × capacity − delivered_today`. That is the full target capacity, minus an aggregate across all chargers.
  - `ev_live_state` (`backend/core/ev_live_state.py`) keeps a last-known plug state but no last-known SoC.
- **Keep-on:** `_apply_keep_on_after_target` (`pipeline.py:390-442`) only fires when `int(target) == 100`.
- **Executor safety timeout** (`executor/engine.py`):
  - Binary chargers (3524-3533): sets `should_charge=False` inside a branch that already requires `not should_charge`. It's a no-op apart from the log line.
  - Current chargers (3881-3891): explicitly log-only.
  - The specs still describe a "30-minute max overrun force-stop".
- **Replan dispatch:** already unified by `ev-goal-lifecycle-feedback`. `ha_socket` (plug and goal changes), the EV API and the executor's `_request_balancer_replan` all call `scheduler_service.request_replan`, which picks `create_task` or `run_coroutine_threadsafe` by calling thread. Nothing remains for this change.
- **Assumed-plugged planning** (`_resolve_ev_charger_plan_state`): an unplugged charger with a goal is planned from its live SoC, else the persisted `current_soc_percent`. `_persist_ev_multi_day_state` writes `current_soc_percent` as `soc or 0.0`, so a missing reading is persisted as 0%.
- **Other cruft:**
  - `ev_shortfall_kwh` is copied into every slot's solver result (`KeplerResultSlot.ev_shortfall_kwh`).
  - The "ready-by without target" warning in `merge_ev_goals_from_state` fires on every planner run.
  - Surplus EV energy terms (reward, energy balance, excess-PV sink cap, and the surplus counted toward the goal requirement) use full `slot_hours` for slot 0, while scheduled EV uses `ev_slot_hours`. (`_ev_day_energy_terms` went away with the quotas.)

## Goals / Non-Goals

**Goals:**
- A truthful EV cost for any period, split into grid and solar, consistent with the card's existing export valuation.
- Never plan against a fabricated SoC. Carry a recent valid reading for a bounded time, then stop and say so.
- Delivered energy attributable per charger.
- Keep-on works at any target.
- Remove dead or duplicated EV code without changing behaviour.

**Non-Goals:**
- Planned or forecast EV cost for a goal. That belongs with the per-day estimate in `ev-planning-model`.
- Changing the headline Net, the import/export pricing model, or the tariff/fee handling.
- Queued or coalesced replans, triggering replans on goal save, and replan dispatch. All delivered by `ev-goal-lifecycle-feedback`.
- Backfilling per-charger energy for history recorded before the migration.

## Decisions

### D1. EV source attribution per slot: grid first
For each slot:
- `ev_grid_kwh = min(ev_charging_kwh, import_kwh)`
- `ev_solar_kwh = ev_charging_kwh − ev_grid_kwh`
- `ev_cost_sek = ev_grid_kwh × import_price`

The EV cost is the grid import cost only, so it is genuinely part of Grid Import. Solar energy is not given a monetary value; the solar share is informational. The user confirmed the grid-first split on 2026-09-25 and the grid-only cost on 2026-09-26 (refinement before commit; it replaced an earlier valuation of solar at the forgone export price).

Rationale:
- Source isolation blocks battery discharge whenever the EV charges, so the EV is fed by grid and PV only.
- Attributing import to the EV first is conservative: it never understates EV cost.
- It needs no fragile house-load disaggregation.
- The cost reuses `import_price_sek_kwh`, exactly as the card's Grid Import does, so the EV figure is a true subset of Grid Import.

Alternatives considered:
- **Proportional split** (EV share of total load × import): hides solar charging when house and EV coincide.
- **PV-first** (EV takes PV before the house): overstates the solar share.
- **Valuing solar at the forgone export price:** mixes an opportunity cost into a figure shown under Grid Import, so it would no longer be a part of that total. Rejected by the user on 2026-09-26.

Computed in SQL next to the existing aggregates. Returned fields:
- `ev_grid_kwh`
- `ev_solar_kwh`
- `ev_cost_sek`
- `ev_solar_share` (0-1, or null when `ev_charging_kwh` = 0)

### D2. The EV row is a breakdown line, not part of Net
The card adds an indented "↳ of which EV" sub-row directly under Grid Import: grid import cost in kr, total EV kWh, and "X% solar".

The EV cost is already inside Grid Import, so the headline Net and the existing rows stay unchanged. The sub-row is labelled "of which", so it isn't double counted.

Visibility (follow-up, user-approved 2026-09-26): the row is always shown when an EV charger is configured (`system.has_ev_charger`, the same flag that drives the rest of the dashboard's EV UI, passed to `GridDomain` by the Dashboard). A range with no EV energy shows "0 kr · 0 kWh" and no solar share. With no charger configured the row is hidden, unless the range still has recorded EV energy (e.g. a charger removed later), so historical cost is never hidden. No API change is needed: the energy endpoints already return zeros.

Explanation: following the card's existing native `title` tooltips, the sub-row explains that the figure is the grid import cost of EV charging, part of Grid Import and not added to Net, with solar not priced; the solar share explains that it is the share of EV energy that came from solar, for information only.

### D3. Per-charger energy in a new table
New table `ev_charger_observations`:
- columns: `slot_start`, `charger_id`, `energy_kwh`, `created_at`
- primary key: (`slot_start`, `charger_id`)

It is written by the store in the same transaction as the `slot_observations` upsert. The aggregate `ev_charging_kwh` stays the sum of the chargers.

Rationale:
- A JSON column on `slot_observations` can't be summed per charger in SQL.
- One column per charger doesn't scale.

Alembic migration, idempotent. This is a DB schema change (AGENTS.md Ask-First); **the user approved it on 2026-09-25.**

Using the new data:
- `_ev_delivered_today_kwh(db_path, charger_id, tz, now)` sums this table for slots starting in `[local midnight of now, now)`, where `now` is the planner's effective time (so `now_override` is honoured). It is a synchronous `sqlite3` read like the one it replaces.
- `_persist_ev_multi_day_state` stores the per-charger value.
- Before the migration, or when no rows exist for today, there is no fallback to the aggregate. The value counts as unknown, and delivered-today is not subtracted.

### D4. Stale SoC: carry, then stop and warn
The live reader returns none on a bad read; that is unchanged. On every valid read, `ev_live_state` records the value and its timestamp as last-known SoC (process memory, like the last-known plug state; after a restart there is no carry until the first valid reading). The planner (`ha_client.get_initial_state`) and the EV API use a resolved SoC:

| Case | Resolved SoC | `soc_status` |
|---|---|---|
| Live SoC valid | The live value | `live` |
| Live SoC none, last-known age ≤ `soc_stale_after_minutes` (default 15, per charger) | The last-known value | `carried` |
| Anything else | None | `stale` |

When `soc_status` is `stale` for a **plugged** charger:
- `required_kwh` is None, so no goal constraint is sent to Kepler for that charger, and no goal charging is planned.
- The EV API reports status `soc_unavailable`, plus `soc_status` and `soc_age_minutes` (the age of the last reading; null when there was none since startup).
- One notification is sent per stale episode, gated by its own toggle `executor.notifications.on_ev_soc_stale` (default `true`). The toggle sits with the existing `executor.notifications.on_*` toggles in `config.default.yaml`, in the notifications section of the settings UI (`frontend/src/pages/settings/types.ts`) and in the Executor page's notification list. It is not tied to `load_balancing.notify_interventions` or any other existing toggle.
  - Episode tracking lives in `ev_live_state` (set by whoever resolves the SoC: planner reads and the EV API; ended by any valid reading or by the charger being unplugged). The executor owns notifications, so on each tick it sends one notification per charger that entered an episode, and forgets the charger when the episode ends.
- Recovery replan (follow-up, user-approved 2026-09-26): when an episode is ended by a valid reading (not by unplug), `ev_live_state` records a pending recovery. On each tick the executor (`_check_ev_soc_stale`) consumes pending recoveries for configured chargers and requests one immediate replan via `scheduler_service.request_replan(ReplanReason.SOC_RECOVERED, charger_ids=[...])` (reason `ev_soc_recovered`), so goal charging resumes without waiting for the scheduled run. Each recovery is consumed once, so there is one replan per episode. When the valid reading is first seen by a planner run itself (`ha_client`), that run already plans from it and discards the pending recovery, avoiding a redundant replan.
- The log says "SoC unavailable for N min — goal charging suspended", not "defaulting to 0%".

The old fallback (full target capacity minus delivered-today) is removed.

Chargers with no SoC sensor configured at all keep today's documented behaviour: a SoC-less estimate using per-charger delivered energy from D3.

Rationale: wrongly planning 60 kWh at peak prices is worse than pausing and telling the user. Surplus charging is not goal-driven, so it continues.

### D4a. Stale SoC vs assumed-plugged planning (rebase decision)
`ev-goal-lifecycle-feedback` D7 plans an unplugged charger's goal from its live SoC or, failing that, the last persisted `current_soc_percent`, with no age limit. Its design already delegates "the stale-SoC timeout for plugged chargers" to this change. The two rules are combined as follows:

- **Plugged chargers:** D4 applies. Live → carried (within the window) → stale (goal suspended, warned).
- **Unplugged chargers (assumed-plugged):** unchanged from D7. Resolved SoC if live/carried, else the persisted SoC regardless of age. No suspension, no `soc_unavailable` status, no notification.

Rationale:
- A car that is away is not expected to report SoC; a stale reading there is normal, not a fault.
- Assumed-plugged slots are planning and display only. The executor never acts on an unplugged charger (plug gating), so an old SoC can never drive real charging.
- The plug-in replan re-plans with the real SoC. If that reading is unavailable, the charger is now plugged and D4 takes over (carry, then suspend and warn).

To keep the persisted value trustworthy, `_persist_ev_multi_day_state` no longer writes a missing SoC as 0%; it keeps the last persisted `current_soc_percent` instead. Otherwise one stale planner run would make a later assumed-plugged plan see an empty battery.

### D5. Keep-on at any target
The condition becomes `resolved_soc >= target_soc_percent`, with SoC status `live` or `carried` (never `stale`). The flagging window (now < end ≤ deadline) is unchanged.

### D6. Cleanup
- **Safety timeout:** delete both blocks and `EVChargerState.charging_started_at`, which only they read. Update the two spec requirements. Stopping when the plan says off is unchanged.
- **Replan dispatch:** already done by `ev-goal-lifecycle-feedback` (`scheduler_service.request_replan`). Verified during rebase; no code change here.
- **Shortfall:** hold the per-charger `ev_shortfall_kwh` once on `KeplerResult` instead of on every slot. Diagnostics read it from there, and the published `ev_goal_diagnostics` is unchanged.
- **Ready-by warning:** log once per (charger, goal fingerprint) per process. The fingerprint is (`ready_by`, `ready_by_date`, `repeat`, `last_updated`).
- **Slot-0 surplus:** the EV surplus reward, the surplus load in the energy balance, the excess-PV sink cap and the surplus counted toward the goal requirement use `ev_slot_hours[t]`.

## Risks / Trade-offs

- **[D1 undercounts solar when the house also imports]:** accepted, because it's conservative, and the label says "grid-first".
- **[The stale-SoC stop could leave a goal short when the SoC sensor is flaky]:** mitigated by the configurable window, the carried value, the visible warning, and planning resuming right after a valid read via the one-per-episode `ev_soc_recovered` replan (D4).
- **[Process restart loses the last-known SoC]:** a plugged charger whose sensor is unavailable right after a restart is treated as stale immediately (no carry). Accepted: conservative, and self-heals on the next valid reading.
- **[The migration on a ~519 MB prod DB]:** it's a new empty table, so no rewrite. Rollback drops the table; the aggregate column is untouched.
- **[Removing the timeout log removes a signal someone might grep for]:** the executor already logs every plan-driven stop.

## Migration Plan

1. Deploy the migration (new table), then deploy the recorder/store writes.
2. Per-charger delivered stays unknown until the first slot is recorded (no backfill).
3. Rollback: revert the code, then downgrade the migration (drop the table).

## Open Questions

None. Resolved on 2026-09-25: the DB schema change is approved, grid-first attribution is confirmed, and the stale-SoC notification gets its own toggle. Resolved during the 2026-09-26 rebase: D4a (staleness applies to plugged chargers only), which follows the boundary already stated in `ev-goal-lifecycle-feedback`'s design.
