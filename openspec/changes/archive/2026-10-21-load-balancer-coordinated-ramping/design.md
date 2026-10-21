## Context

Balancer logic lives in `executor/load_balancer.py` (pure decisions, `LoadBalancer.tick`) and is wired in `executor/engine.py`. Verified problem sites (line numbers approximate): plan bypass `if cap >= planned` and cleared cap state (LB ~1096, ENG ~3440-3470); `own_draw` only for EV (LB ~1163-1174); `granted_increase` rebuilt per tick (LB ~1179); shed restore `avg_ok(phases, 0.0)` (LB ~1229); shed on `pool_headroom<0` (LB ~1342) vs charger debounce (LB ~874); battery early return (LB ~1028) and `min(cap, import, measured)` (ENG ~3443); stale battery hold (LB ~1004-1015); `abs()` (ENG ~2798); nominal voltage (LB ~979); writes (actions.py ~775, ~1364); replan (ENG ~3696-3773). Planner: only EV uses `first_slot_remaining_h` (kepler.py ~131); other flows/limits use full slot h. Implementers must re-verify lines before editing.

## Goals / Non-Goals

Goals: no overshoot from coordinated ramps, no restore oscillation, fewer actuator writes, plans valid for the partial slot, observable decisions. Universal, data-driven, safe fallbacks; no values tuned to one installation.
Non-Goals: time-current fuse model (`fuse-overload-timing`), full per-phase planner awareness, 1-phase inverters.

## Decisions

**D1 Pending-increase ledger.** A `PendingLedger` in the balancer state keeps per entry: granted amperes per phase, granted value, timestamp. Expiry: measured value within one profile step of granted, or `pending_timeout_s` (default 60). Reduction clears the item. Alternative: widen the averaging window (rejected, slows all ramps and still ignores unmeasured grants). Alternative: single global "one increase per N s" (rejected, ignores available room, starves).

**D2 One room gate per tick.** A single function `grant_increase(entry, wanted_a)` computes room = target_margin x fuse minus averaged current minus ledger sum minus same-tick grants, bounded by momentary headroom. All paths call it (ramp, plan step-up, resume, restore, 1-phase to 3-phase). Entries are visited in reverse give-way order (rearmost restores first), so the budget is shared, not stepped independently.

**D3 Battery plan changes.** Plan decreases apply immediately; increases are capped by cap+step via D2. Cap state is never cleared when cap equals plan, it is kept so the next plan jump ramps.

**D4 Restore by power.** `ShedLoadInput` gains `power_w` and `power_source` (sensor, configured, worst_case). Restore needs room for that power on each phase via D2. Fallback worst case = full `main_fuse_a`. Custom loads get optional `power_kw`/`power_sensor` (no migration). Alternative: learn power from the last on-period (kept as follow-up, open question 3).

**D5 Shed ordering.** Shed pass runs only after entries above have completed debounce, consuming the same debounce state; severe-overload rule unchanged.

**D6 Fresh samples.** Track per-phase last sample id (timestamp+value) and estimated cadence (median of recent gaps, bounded). A cut is permitted once per sample id per phase; after a cut the phase is "awaiting response" until the actuator's measured value settles or a response timeout of two detected sensor intervals (capped at 15 s) passes, after which a still-overloaded fresh sample cuts again; relief already ordered counts in the pool meanwhile. First cut on a fresh overloaded sample is immediate (safety).

**D7 Battery cut independent of lag.** reducible = min(cap, import) ignoring a lagging measured charge. Measured charge only drives response detection (D6) and avoids cutting below actual draw.

**D8 Battery resume.** Reuse the EV escalation helper (10, 30, 120 s, reset after stable period). Resume at profile minimum, then ramp via D2.

**D9 Battery stale fail-safe.** Same ladder as EV: min charge immediately, pause after `resume_delay_s`.

**D10 Anti-wear.** Adaptive step pacing: an actuator's next increase is allowed once its previous step has settled in the measured value (ledger, D1), or after `max_step_interval_s` (default 30) when it cannot be measured or does not settle. A fast inverter ramps at its own pace; a slow or unknown one at most one step per 30 s. Write layer (`actions.py`) keeps per-actuator `last_write_at` and a deadband `write_deadband_percent` default 2 (never smaller than one profile step); reductions flagged `urgent=True` bypass pacing and deadband. Alternative: fixed minimum interval (rejected, too slow for fast actuators and too fast for slow ones). Water heater/custom `min_on_s`/`min_off_s` default 300; overload shed immediate, restore waits min off. Alternative: only smoothing the plan (rejected, wear also comes from balancer ramps).

**D11 Voltage and sign.** Battery W/A uses measured phase voltage when fresh, else nominal. `phase_sign` default `import_positive`, negative becomes 0 A.

**D12 Remove balancer replan.** Delete tracking, trigger and config key; migration drops the key; template, UI and docs updated. Rationale: plan lacks fuse info and cannot reduce balancer-caused throttling; it fired every 30 min and consumed the manual-charge replan slot.

**D13 Planner remaining-time basis.** Compute `slot0_h = remaining` once and pass it as the duration of slot 0 to every term (energy balance, limits, fuse row, surplus sink, costs). Adapter scales slot-0 load/PV/water/custom forecasts by `remaining/slot`. Output kW = kWh / remaining for slot 0. Use floor in the `now_override` path. Alternative: keep full-slot math and clamp kW afterwards (rejected, SoC trajectory and costs stay wrong).

**D14 Observability.** `BalancerTrace` ring buffer (default 600 ticks, memory-bounded) plus INFO logs on decision change only; exported as `balancer_trace.json` in the diagnostics bundle, with a manifest entry.

**D15 Pluggable trigger.** `relief_needed(phase_state) -> Relief(amount_a, urgent)` is the only place overload is detected. Compatibility with `fuse-overload-timing`: it replaces this function and replaces `pause_debounce_s` consumption in D5. Both changes touch phase-load-balancing; apply order is free, but whichever lands second rebases the D5 wording. The overlapping requirement is "Pause below minimum current with anti-flap resume" (not modified here).

## Risks / Trade-offs

- Ledger too conservative slows ramps: bounded by timeout and settle detection; covered by simulation test.
- Sensor cadence detection wrong: fallback to value-and-time pairs; unknown cadence treated as one tick.
- Sign convention change could mis-handle users whose meter reports import as negative (abs masked this): warn at startup when a phase is persistently negative while loads are charging; `phase_sign` fixes it (see open question 1).
- Partial-slot planning changes plans in the last minutes of a slot only; boundary plans identical.
- Removing the replan: a persistent overload is handled only by balancer giving way; plans respect fuse only via the existing EV constraint until per-phase planner awareness lands.

## Migration Plan

Config migration drops `replan_after_throttled_s` (idempotent, logged). New keys have defaults via the template merge. No schema change. Rollback: revert; the dropped key had no other consumers.

## Resolved Questions (maintainer, 2026-10-21)

1. `phase_sign` default `import_positive`; negative becomes 0 A; startup warning when a phase stays negative while loads charge.
2. Inverter/EV pacing is adaptive (settle-based) with `max_step_interval_s` 30 s as upper bound; water heater and custom switch `min_on_s`/`min_off_s` 300 s.
3. Learning shed-load power from observed draw is deferred; the worst-case fallback is safe.
4. Balancer trace: 600 ticks, in memory only.
5. Docs in `docs/` may be updated, limited to the removed and new settings.

## Implementation Notes (apply, 2026-10-21)

Clarifications and the few places where the implementation refines the text above.

- **Settle tolerance (D1).** "Within one profile step" is bounded by half the granted increment: the item settles when `measured >= granted - min(step, increment / 2)`. A plain one-step tolerance would count the pre-step value as settled for the 1 A EV step. EV measures the raw measured draw (not the settle-protected baseline), the battery its measured charge; shed restores have no measurement and expire by `pending_timeout_s`.
- **Battery counted at its latest draw.** Like the chargers, the battery enters the averaged current at its latest draw (measured, else the applied cap), so the 60 s averaging lag does not hide a ramp once its ledger item has settled.
- **Worst-case restore (D4).** A load with unknown power restores only when `avg + pending == 0 A` on its phases, and counts as a full `main_fuse_a` in the ledger until it expires. The live power sensor only counts while it reads at least 50 W; a shed load reads about 0 W, so in practice the configured power (or the worst case) is used for the restore decision. Learning the power stays deferred.
- **Fresh start of grid charging.** An existing measured charge becomes the initial cap. With no observed charge, the battery starts from zero, confirms room, resumes at its minimum through the shared gate and then ramps.
- **Urgent overloads (D6).** Severe overloads retain the immediate pause/debounce rule, but all reductions obey one cut per fresh phase sample and the bounded response wait. Emergency writes bypass pacing and deadband.
- **Pacing location (D10).** Adaptive step pacing lives in the balancer (ledger item age against `max_step_interval_s`), because only the balancer knows when a step has settled. The write layer keeps `last_write_at`, the deadband (never below one profile step, only while load balancing is enabled) and the urgent bypass; the EV current deadband is one ampere, so it never blocks an integer step.
- **Restore arbitration (D2).** A shed entry explicitly planned off does not block higher-listed restores: it has no restore demand until its plan requests on.
- **Minimum on/off times (D10).** Balanced water heaters and custom excess-PV switches send plan switching through the same reverse-order restore pass and min-on/off clocks. The custom excess-PV write is skipped when the entity is balanced, so it cannot override a shed. Overload sheds remain immediate.
- **Startup state (D2/D10).** Balanced heaters read each device's actual switch/temperature target (reuse the first-heater read where possible). Binary shed chargers read their actual switch state and use the same plan intent as dispatch. Missing/unreadable state enters the shared restore gate conservatively; the legacy aggregate water-temperature default is never evidence that a heater is on.
- **Binary charger power.** `ev_chargers[].rated_power_kw` (existing config key) is now parsed by the executor and is the configured restore power of a shed binary charger.
- **Slot-0 duration (D13).** Positive remaining durations, including the last seconds of a slot, are used exactly. Only an exactly elapsed duration has a numerical floor of one microsecond to avoid division by zero.
- **Replan plumbing.** `_request_balancer_replan`, `_executor_replan_allowed` and `ReplanReason.LOAD_BALANCER` keep their names: the manual-charge-end and EV failure/recovery replans still use them. Only the balancer-triggered caller and its tracking were removed.
- **Docs.** No file under `docs/` mentioned `replan_after_throttled_s`; `docs/USER_MANUAL.md` gained a short section for the new keys.

The delta explicitly amends the older severe same-tick shed-plus-EV scenarios: severity still bypasses pause debounce, but the new one-cut-per-fresh-phase-sample and bounded response guards apply. This reconciles the main spec with D6 and the maintainer's explicit key point; main specs remain unchanged until a separate sync.
