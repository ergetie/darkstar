## Context

`executor/engine.py` (~1915-1988) reads `input_sensors.grid_current_l1/l2/l3` every tick via `ha.get_state(entity)`, which already returns the full HA state payload (`state`, `attributes`, `last_updated`, `last_changed`) — today only `state` and the timestamps are used; `attributes.unit_of_measurement`/`attributes.device_class` are discarded. The balancer (`executor/load_balancer.py`) treats every phase reading as amps directly, with no unit awareness and no voltage concept anywhere in AC config (the only existing `voltage_v` fields are unrelated DC battery voltage).

`load_balancing.loads[]` today accepts `device_type: "ev_charger"` regardless of the charger's `type` field. The frontend `BalancedLoadsEditor.tsx` device picker (`deviceOptionsFor`) lists all EV chargers with no type filter. But `executor/engine.py`'s per-device control loop (`_control_ev_chargers`) branches on `is_current_type` and `continue`s to a separate, always-on control path (`_control_ev_charger_current`) before the shed-list check (`shed_binary_charger_ids`) is ever reached — so a `type: current` charger referenced in `loads[]` is accepted by validation and the UI but has zero effect. Separately, `EVBalancerInput` (the struct `load_balancer.py` uses for the always-on throttle path) has no priority field — multiple `type: current` chargers sharing a phase are each throttled independently against the same tick's headroom snapshot, with no ordering between them.

## Goals / Non-Goals

**Goals:**
- Let a phase's grid measurement be either a current sensor or a power sensor, auto-detected, with power converted via voltage (real per-phase sensor or nominal fallback).
- Make the existing two-tier balancing structure (continuous EV throttling always precedes on/off shedding) visible and correctly gated in the UI, instead of a picker that silently accepts a control that does nothing.
- Let multiple dynamically-throttled EV chargers be ranked against each other for fairness when sharing an overloaded phase.
- Zero behavior change for existing users who only configure current sensors and a single EV charger.

**Non-Goals:**
- Unifying continuous-throttle and on/off-shed into one interleaved priority list (backlogged as a Future Idea — see `docs/BACKLOG.md`).
- Power/current ambiguity on the EV charger's own actuation entity (`current_entity`) — this change only touches the three grid measurement sensors.
- Per-load power-factor configuration — the `I = P / V` conversion assumes ~unity power factor, documented as a known approximation.

## Decisions

**1. Auto-detect sensor kind from HA metadata, not a manual toggle.**
`attributes.unit_of_measurement` (primary) and `attributes.device_class` (secondary confirmation) are read from the same state payload the executor already fetches every tick — no new sensor plumbing, self-healing if a user swaps the entity later. Alternative considered: an explicit per-phase mode toggle in settings — rejected because it's an extra setting that can drift out of sync with what's actually wired (toggle says "current" but entity is a power sensor), whereas the unit is ground truth. Unrecognized units are a hard validation error, not a silent guess, because guessing wrong on a fuse-protection input is worse than failing loudly.

**2. Normalize W/kW before conversion; unit lookup happens per tick, not cached at config time.**
Because entity metadata is read live each tick (see Decision 1), unit normalization (W → kW or vice versa) happens in the same read path, keeping detection and conversion co-located and self-correcting if HA changes an entity's reported unit.

**3. Voltage fallback boundary: absence vs. staleness are different failure semantics.**
- No voltage entity configured for a phase at all → use `load_balancing.nominal_voltage_v` (default 220) permanently. This is a design-time absence, not a fault.
- A voltage entity **is** configured but its reading is missing/stale → do **not** silently substitute the nominal value. Feed it into the existing stale-sensor fail-safe (`sensor_stale_after_s` → force `min_current_a` → pause after `resume_delay_s`), using the *older* of the phase's power-reading timestamp and voltage-reading timestamp. Rationale (explicit user decision): a configured-but-stale sensor means something is actually wrong, which should degrade the same way any other stale grid input does, not be masked by a plausible-looking fallback number.

**4. 220V nominal default is deliberately biased low, not "textbook" 230V.**
Grid voltage sags under load, and sag coincides with exactly the moment this feature exists to protect (near the fuse limit). `I = P / V_nominal` with a fixed 230V *under-reports* current during a sag — the wrong direction for a safety loop. 220V sits inside the normal EN 50160 tolerance band (230V ±10% → 207-253V) while erring toward assuming slightly more current than there may really be.

**5. Remove `type: current` chargers from the shed-list picker entirely; surface them in a separate, always-populated group instead.**
Alternative considered: leave the picker as-is and just fix the label/add a validation error — rejected as "not optimal UX" (explicit user feedback): the charger already IS being balanced (via the always-on throttle path), so hiding that from the Load Balancing tab and only exposing a non-functional shed option was the actual bug. The fix is to show the real mechanism (a priority-ranked, always-on throttle group) rather than gate access to a fake one.

**6. Two-tier structure (throttle-group always precedes shed-list) is kept, not unified, and made explicit in the UI via two labeled sections.**
Unifying was considered (see BACKLOG.md addition) and deferred: it requires redefining how a continuous throttle-step compares to a full on/off shed when ranked together, and reworking `load_balancer.py`'s `tick()` gate (`ev_at_floor_or_paused`) into an interleaved resolver — materially bigger than this change's scope. Shipping the existing two-tier behavior with explicit labeling gets the correctness/visibility fix now without the larger rewrite.

**7. Priority within the throttle group: sequential allocation, lower number gives way first, fully to floor before the next charger is touched.**
Consistent with the existing shed-list convention (lower priority number sheds/gives-way first). Explicit user decision: a charger throttles all the way to its floor before the next-priority charger absorbs any of the remaining overload — no partial/proportional sharing between chargers in the same tick. `load_balancer.py`'s per-EV loop changes from independent-per-charger (each computes its own reduction against the raw shared headroom) to priority-ordered sequential allocation (each charger's allocation reduces the headroom pool available to the next).

## Risks / Trade-offs

- **[Power-factor assumption]** `I = P / V` assumes ~unity power factor. Accurate for EV chargers/resistive loads; drifts for reactive loads. → Mitigation: document as a known approximation in the spec; current-sensor mode remains available and preferred when possible.
- **[Behavioral change for `loads[]` validation]** Existing configs that (harmlessly, silently) reference a `type: current` charger in `load_balancing.loads[]` will start failing startup validation. → Mitigation: this was always a no-op, so no real behavior changes for any user; the validation error message points directly at the new throttle group so the fix is a one-line config move (or simply removing the now-invalid entry, since the charger was already being throttled automatically).
- **[Priority-ordering algorithm change]** Moving from independent-per-charger reduction to sequential-by-priority changes exact tick-by-tick amperage decisions for any household with 2+ `type: current` chargers sharing a phase (rare today, but possible). → Mitigation: single-charger households (the common case) see no change; document the new ordering clearly in the spec and settings UI helper text.
- **[Two-sensor staleness complexity]** Tracking staleness across a power+voltage pair per phase is more state than today's single-sensor-per-phase tracking. → Mitigation: reuse the existing per-phase staleness data structure, just feed it `min(power_updated_at, voltage_updated_at)` per phase instead of a single timestamp.

## Migration Plan

- Fully additive/backward compatible for sensor config: existing `grid_current_l1/2/3`-only setups are unaffected (unit detection resolves to "current", same as today's implicit assumption).
- `load_balancing.nominal_voltage_v` ships with a default (220), so no config file needs to change for the feature to keep working.
- The one behavior change (rejecting `type: current` chargers from `loads[]`) surfaces as a clear startup validation error, not a silent failure or crash — any affected user (unlikely, since it was already a no-op) gets actionable guidance on their next config reload.
- No data migration, no API versioning concerns — this is executor/config/settings-UI scoped only.

## Open Questions

None outstanding — all design questions from the exploration phase (auto-detect vs. toggle, voltage fallback boundary, nominal voltage value, picker fix, priority semantics) were resolved with the user before this document was written.
