# Design: Universal Load Balancing + EV Current Control

## Context

Darkstar's executor ticks on `executor.interval_seconds` (production will run 5 s; per-phase grid sensors update every 5 s at the grid connection point). Each tick it loads the current 15-min slot, gathers `SystemState` (aggregate kW values only today), evaluates overrides, makes a controller decision, and dispatches HA service calls. EV charging is actuated as binary ON/OFF (`_control_ev_charger` → `set_ev_charger_switch`) even though the planner already delivers per-slot, per-device kW plans (`ev_charger_plans`). There is no per-phase data, no fuse rating, and no mechanism to reduce (rather than stop) any load. A dormant `executor.ev_charger` config stub (`control_mode: current`, `control_entity`, `max_current_a`) exists but is consumed nowhere.

The physical setup this must protect: 3-phase house, per-phase main fuse (user: 20 A), 3-phase EV charger (user: go-e Gemini Flex 16 A, exposed via HA/MQTT as entities). All ratings and entities must be configurable per user; everybody in the target market (Sweden) has 3-phase.

## Goals / Non-Goals

**Goals:**
- Keep every phase's grid current at/below the configured main fuse rating in real time, with the EV charger as the primary throttle and prioritized on/off shedding as the fallback.
- Replace binary EV control with an ampere setpoint for chargers configured as `current` type, reusable later by the excess-PV dispatcher (Change 2).
- Anti-flapping so charging does not sawtooth (pause → 120 s + margin before resume; slow ramp-up).
- Fail safe: stale/missing phase data must never result in unbounded charging.
- Make 5 s executor ticks operationally sane (execution-log throttling).
- Settings UI + live per-phase status view.

**Non-Goals:**
- 1↔3-phase mode switching and excess-PV EV dispatch (Change 2 — but the amp actuation path built here is its foundation).
- Battery-assist fuse protection (Change 3).
- Effekttariff / peak-shaving on total kW (paused in Sweden; `grid.import_limit_kw` stays unused).
- Deprecating `system.grid.max_power_kw` (later change; it remains the planner's import budget).
- Controlling the charger's own fallback settings (user configures charger-side fallback in the go-e app; Darkstar just documents the recommendation).

## Decisions

### D1. Balancer is a final capping stage in the executor tick, not a new loop
Runs inside the existing `_tick` after the controller decision and override evaluation, immediately before dispatch: it takes the intended EV amp setpoint (and shed-able load states) and caps them against per-phase headroom. No separate thread/loop — the user simply lowers `executor.interval_seconds` (5 s in production). *Alternative rejected:* dedicated fast loop — more moving parts, and 5 s grid sensors bound reaction time anyway. The charger's own load-fallback covers total Darkstar/HA failure.

### D2. Per-phase headroom math in ampere, feedback-based
Per tick, for each phase p: `headroom_a[p] = main_fuse_a − grid_current_a[p]` (measured current already includes the EV). New EV setpoint = current setpoint + `min(headroom_a[p] over the phases the EV draws on)`, clamped to `[min_current_a, effective_max]` where `effective_max = min(charger max_current_a, planner-derived amps)`. Fuse loading uses current magnitude (a fuse heats on |I| regardless of direction). *Alternative rejected:* computing "house load minus EV" from scratch each tick — the feedback form is simpler and self-correcting against measurement drift.

### D3. Decrease fast, increase slow
Decreases apply immediately and unbounded (safety). Increases are rate-limited (default 1 A per tick) and only allowed when all relevant phases are below `resume_margin_percent` of the fuse. After a balancer-initiated pause (headroom < 6 A floor), charging resumes only after `resume_delay_s` (default 120 s) **and** margin is satisfied. All three are config keys. This is the anti-sawtooth core.

### D4. Phase awareness comes from measurement, not assumption
Which phases the EV actually loads is read from the charger's per-phase power/current sensors in HA (cars may draw 1, 2, or 3 phases regardless of charger wiring). Before first measurement, assume the configured phase assignment. On/off balanced loads use their user-declared phase list (the user knows which phase the water heater is on). Custom loads follow the same declaration pattern as `ExcessPVCustomEntityConfig` (entity + on/off values + phases + priority).

### D5. Shedding order and restore order
When the EV is already at its floor (or paused) and a phase is still over the fuse, shed on/off loads in ascending priority (lowest priority first) among loads declared on the overloaded phase(s). Restore in reverse order, subject to the same margin + delay rules. Water heater shed = write its minimum safe target temperature via the existing actuation path (no new hardware assumptions); custom entity shed = write its off value. The balancer's writes take precedence over the schedule for that tick; normal control resumes automatically once restored.

### D6. EV current actuation extends `ev_chargers[]`, retires the legacy stub
Per-device fields: `type: current` (alongside existing `binary`), `current_entity` (HA number), `min_current_a` (default 6), `max_current_a`, `phases`. kW→A: `amps = floor(planned_kw × 1000 / (230 × active_phases))`. The dormant singular `executor.ev_charger` stub is removed with a config migration that maps its fields onto the first `ev_chargers[]` device if present. Binary devices are untouched. Existing EV source isolation (no battery discharge into EV) and the 30-min safety timeout are preserved for both types.

### D7. Fail-safe gating and staleness
`load_balancing.enabled` (global key) requires: `system.grid.main_fuse_a` set, per-phase grid current sensors configured (`input_sensors.grid_current_l1/l2/l3`), and at least one balanced load — validated at startup with actionable errors. At runtime, if phase sensor data is missing/stale beyond `sensor_stale_after_s` (default 30 s), the balancer forces the EV to `min_current_a` and, if staleness persists one full resume cycle, pauses it. Balancing disabled ⇒ behavior identical to today (external-balancer users unaffected).

### D8. Execution-log throttling
`log_execution` writes only when the tick produced a change (mode intent, any dispatched action, override/balancer state transition) plus a heartbeat row at least once per 15-min slot. Balancer state transitions (throttle start/stop, shed/restore, pause/resume, stale-data fallback) are always logged with a reason string. Keeps ~5 s ticks from writing ~17k identical rows/day while preserving the audit trail the UI reads.

### D9. Status surface reuses the live-metrics path
Per-phase currents, fuse headroom, balancer state (limiting/shedding/paused + reason, current EV setpoint vs. planned) are added to the existing WebSocket live-metrics emission and a small REST status endpoint for the settings/status page. No new transport.

## Risks / Trade-offs

- [5 s ticks multiply HA REST reads] → State gathering at 5 s is a handful of entity reads; reuse already-connected WS values where available; measure tick duration (already recorded as `duration_ms`) and document a minimum supported interval.
- [Charger reaction latency (MQTT round-trip, car's onboard charger ramp)] → Decrease-fast/increase-slow asymmetry plus resume margin keeps transient overshoot short; per-phase fuses tolerate brief moderate overload (thermal curve). Document that sub-fuse-rating protection is best-effort, not a certified protection device.
- [Sensor sign/unit conventions differ per inverter] → Normalize via existing unit-aware sensor reads; validation rejects obviously wrong values (e.g. negative fuse, currents in kA); use magnitudes for fuse loading.
- [Throttled logging could hide activity from existing consumers] → Heartbeat row per slot + always-log state transitions; verify UI history views against the new pattern.
- [User misdeclares water-heater phase] → Worst case the balancer sheds a load that doesn't help; the EV floor/pause path still protects the fuse. UI copy must explain phase declaration.
- [Planner unaware of balancer caps] → Accepted for v1: the planner may schedule energy the balancer then trims; executed kWh is already recorded and future replans self-correct. Cross-feeding balancer state into planning is future work.

## Migration Plan

1. Config migration: add new keys with safe defaults (`load_balancing.enabled: false` — feature is opt-in); map legacy `executor.ev_charger` stub onto `ev_chargers[0]` if present, then drop the stub.
2. Deploy with balancing disabled; verify binary EV control unchanged (regression).
3. User configures fuse, phase sensors, balanced loads; enables `type: current` on the go-e device once installed; flips the global toggle.
4. Rollback = set `load_balancing.enabled: false` (single key); EV falls back to binary/scheduled behavior.

## Open Questions

- None blocking. Entity IDs for the go-e charger are configured after hardware installation (explicitly deferred). Exact UI layout details are settled at implementation within the existing settings framework.
