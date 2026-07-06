# Design: Load Balancing Completion

## Context

The shipped balancer (`executor/load_balancer.py`) uses a fixed two-tier give-way order: every `type: current` EV charger throttles to its floor (ranked among chargers by `load_balancing.charger_priority`), and only when all chargers are at floor or paused does the on/off shed list (`loads[]`, ranked by its own `priority` field) activate (`ev_at_floor_or_paused` gate in `tick()`). Darkstar serves multiple households with different preferences — some want the water heater shed before the EV slows — so the fixed ordering (and the two disconnected numeric priority fields) must become one user-ordered list.

Around it, several truthfulness/clarity gaps were identified (2026-07-06 investigation):

- Balancer reaction speed and live-status frequency both equal `executor.interval_seconds` (status is emitted once per tick from `executor/engine.py` ~1408); the shipped default of 300 s makes fuse protection nearly useless and nothing warns about it. Prod runs 5 s; dev ran 60 s and looked frozen.
- The status card is fully live but renders `0.0A / 16A` indefinitely on zero-export homes (Deye keeps grid ≈ 0 W), indistinguishable from a dead socket. The execution history page is near-empty by design (change-only logging + heartbeat per slot) and doesn't say so.
- The planner learns of throttling shortfall only via the live SoC re-read on its next scheduled run (default 30 min); no event-driven path exists. A `type: current` charger without a SoC sensor silently plans from `soc_percent = 0.0`.
- "Current (dynamic amps)" in the EV tab silently enrolls the charger into the balancer's throttled group in another tab, with no explanation at the point of choice.

The deferred `excess-pv-priority-dispatch` change depends on this one and will reuse the ordered-list UI widget and the clarified charger-type UX.

## Goals / Non-Goals

**Goals:**
- One flat, user-ordered give-way list mixing chargers and shed loads; default/migrated order reproduces today's two-tier behavior exactly.
- Config migration from `charger_priority` + `loads[].priority` with no user action.
- Sustained-throttle early replan; balancer intervention notifications; slow-tick and no-SoC warnings.
- UI that is truthful when quiet (liveness indicator, history explainer) and self-explanatory at the point of configuration (EV tab explainer, plain-language give-way rows).
- Ordered-list editor built as a reusable component.

**Non-Goals:**
- Planner awareness of the per-phase fuse constraint (backlog: "Planner Awareness of Sustained Phase Overload").
- Full support for chargers without a SoC sensor (backlog item; only a warning ships).
- Battery-assist during fuse stress (backlog, deferred with revisit triggers).
- The excess-PV priority dispatch change itself (separate, depends on this one).
- Changing balancer physics: headroom computation, asymmetric ramping, anti-flap timers, stale fail-safe all stay as specced.

## Decisions

### D1. Config shape: `loads[]` keeps definitions, a new `give_way_order[]` holds only the ordering
`load_balancing.loads[]` keeps its entries (device_type, device_id, phases, entity, on/off values) but loses `priority`. A new `load_balancing.give_way_order[]` is an ordered list of references — `{kind: charger, id: <ev_chargers[].id>}` or `{kind: shed, id: <loads[].device_id>}` — top gives way first. `charger_priority` is removed. Self-healing on load: current-type chargers missing from the list are appended after the last charger entry (before any shed entry if none exists); shed loads missing are appended at the end; entries referencing devices that no longer exist (or chargers switched back to binary) are dropped with a logged warning. This keeps device definitions where they belong and makes the order a single, obvious artifact. *Alternative rejected:* embedding full load definitions in one ordered list — duplicates the charger config owned by `ev_chargers[]` and makes migration/self-healing messier.

**Migration** (`backend/config_migration.py`): `give_way_order` = current-type chargers sorted by old `charger_priority` (fallback: position in `ev_chargers[]`), followed by `loads[]` entries sorted by old `priority` ascending (lower priority gave way first in both old lists). Old keys are dropped. Idempotent, logged.

### D2. Resolver: single top-down pass, position-aware pausing
`tick()` walks `give_way_order` from the top for each tick with a deficit. Each entry drawing on an overloaded phase gives way fully before the next entry is touched:
- A **charger** entry absorbs the deficit by immediate setpoint reduction down to its floor (`min_current_a`), same-tick, as today. If the deficit persists on a later tick and this charger is the frontmost non-exhausted entry, it **pauses** — pausing is now position-aware instead of a global "headroom < min" rule, which is exactly what lets a user protect a shed load above a charger.
- A **shed** entry gives way by switching off (existing actuation per device type); its relief is measured on subsequent ticks rather than estimated.

An entry is "exhausted" when the charger is paused or the load is shed. Restore runs in exact reverse list order, gated by the unchanged resume delay + margin rules. With the default/migrated order (all chargers first), behavior is tick-for-tick equivalent to the two-tier system; the existing e2e dry-run tests are re-pointed at the default order to prove it. *Alternative rejected:* proportional/interleaved partial give-way across entries — impossible to explain in the UI ("top gives way first" is the whole mental model) and no user asked for it.

### D3. Early replan reuses the plug/unplug replan path
The engine tracks, per charger, the continuous duration in which the balancer's setpoint is below the planner target (or the charger is balancer-paused) while the plan wants charging. When it exceeds `load_balancing.replan_after_throttled_s` (default 600, advanced), the executor requests one replan through the same mechanism the plug/unplug triggers use, then rearms only after a full planner interval has passed — at most one balancer-triggered replan per interval. Timer resets whenever the setpoint reaches the target. *Alternative rejected:* feeding available headroom into the planner — a dynamic constraint goes stale within minutes (recorded in the backlog with rationale).

### D4. Notifications piggyback on existing state-transition logging
The balancer already logs every state transition with a human-readable reason (spec: "Execution log throttling"). Notification dispatch hooks the same transitions, filtered to **shed**, **pause**, and **stale-fallback** (not routine throttle/ramp adjustments — spam), routed through the existing dispatcher/`backend/notify.py` path (HA notify, Discord fallback). Gated by `load_balancing.notify_interventions` (default false), surfaced as a toggle in the settings UI. One notification per transition, not per tick.

### D5. Slow-tick warning, not error
When `load_balancing.enabled` and `executor.interval_seconds` > 15, startup validation emits a **warning** (not a hard failure — shadow-mode and test setups legitimately run slow), and the Load Balancing settings tab shows a persistent inline warning naming both keys and the recommended value (≤ 15 s, 5 s typical). *Alternative rejected:* a hard validation error — would brick existing configs on upgrade; and a separate fast balancer loop — heavier architecture for a problem a one-line config change solves (prod already runs 5 s).

### D6. One reusable `OrderedListEditor` component
A generic drag-to-reorder list component (pointer-based drag with keyboard/button fallback — no new heavy dependency; up/down buttons remain for accessibility) that renders caller-supplied row content and emits the new order. The give-way list uses it now; the excess-PV sink list editor consumes it later. Give-way rows: drag handle, name, phase badges, plain-language capability line ("Throttle 16 → 6 A, then pause" derived from the charger's min/max; "Switch off" for shed loads), and for chargers a "configured in EV tab →" link with everything but position read-only.

### D7. Truthful-when-quiet UI
- **Status card**: show "updated Xs ago" derived from the `live_metrics` payload timestamp (already emitted per tick), with a subtle stale style when the age exceeds a few tick intervals. Keep `toFixed(1)` bars but add the raw measurement as secondary text so near-zero homes see life in the numbers.
- **Execution history page**: header line rendering last tick time and last action/skip reason (already available from executor status), plus static copy: changes and one heartbeat per slot are recorded by design.

### D8. No-SoC warning at validation and in the EV tab
When an `ev_chargers[]` entry has `type: current` and no `soc_sensor`, emit a validation warning and an inline EV-tab hint: Darkstar cannot track charging progress or recover throttling shortfall for this car (plan-time SoC silently assumes 0%). Non-blocking — modern EVs have the sensor; the warning catches forgotten config.

### D9. EV tab label and explainer
Rename the option label from "Current (dynamic amps)" to "Dynamic current (adjustable amps)" and render a short consequence list under the selector when chosen: the planner sets the charge current per slot; the charger is automatically load-balanced (link to the Load Balancing tab); it becomes eligible for future PV-surplus charging. The config value `current` is unchanged — this is presentation only.

## Risks / Trade-offs

- [Resolver rewrite regresses single-charger behavior] → default/migrated order reproduces the two-tier order; existing e2e dry-run tests are kept and must pass unchanged in that configuration; new tests cover shed-above-charger orders and position-aware pausing.
- [Position-aware pausing changes semantics for existing users] → only when a shed load is deliberately ordered above a charger, which is impossible to express today; migrated configs keep chargers first, hence identical behavior.
- [Config migration drops or misorders entries] → migration is pure and unit-tested against: both old fields set, only one set, ties, references to missing devices; self-healing on load covers post-migration drift (charger added/retyped later).
- [Drag-and-drop is fiddly on touch/small screens] → up/down buttons always present; drag is progressive enhancement.
- [Replan trigger fires during normal PV/price throttling by other subsystems] → the timer measures only balancer-caused deviation (balancer setpoint < planner target), not planner-intended reductions; paused-by-plan slots don't count.
- [Notification spam during a flappy evening] → transitions only, shed/pause/stale only, and the anti-flap timers already bound transition frequency; default off.
- [Warning fatigue] → both new warnings (slow tick, no SoC) are one-line, actionable, and name the exact keys/tabs to fix.

## Migration Plan

1. Config migration runs at startup (idempotent, logged): build `give_way_order` from `charger_priority` + `loads[].priority`, drop both old fields. `openspec` specs updated via the delta specs in this change.
2. Balancer resolver swaps behind the same `load_balancing.enabled` gate; disabled installs see zero behavior change.
3. Frontend ships the new list UI reading/writing only the new schema (the backend has migrated by the time the UI loads).
4. Rollback: revert the code; a `give_way_order`-shaped config still runs on the old build only if the old fields are restored — document in the change notes that rollback requires restoring the config backup the migration writes (existing durable-config-write backup path).

## Open Questions

- None blocking. The exact plain-language row copy and the "updated Xs ago" staleness threshold are presentation details to settle during implementation; the 10-min replan default and 15-s tick threshold are tunable config defaults.
