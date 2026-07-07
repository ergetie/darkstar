# Proposal: Excess PV Priority Dispatch

## Why

Darkstar's excess-PV dispatch supports exactly one sink (water heater boost *or* one custom entity) and cannot send surplus solar to the EV at all. With an EV charger arriving (go-e Gemini Flex, variable current control landing in the `universal-load-balancing` change), surplus PV should charge the car once the house battery is full — and the user, not the code, should decide the order in which surplus flows to the available sinks (e.g. house battery → EV → water heater → custom entity). Additionally, a 3-phase charger cannot charge below ~4.1 kW (6 A × 3 phases), so summer days with 2–4 kW of surplus can put nothing into the car unless the charger is switched to 1-phase mode (minimum ~1.4 kW). The go-e charger supports commanded 1↔3-phase switching; Darkstar must drive it.

## What Changes

- **Priority-ordered sink list replaces the single sink.** `executor.excess_pv.sink` (one of `water_heater_boost | custom_entity | disabled`) becomes an ordered priority array of sinks, each individually configurable. The house battery always has implicit first priority (existing SoC-threshold gate is unchanged). Multiple sinks may be active in the same slot when surplus is large enough; priority decides who is fed first. Config migration maps the legacy single-sink key onto a one-element array. **BREAKING** for the config schema (migrated automatically, no user action).
- **New sink: EV surplus charging.** Planner side: the Kepler MILP gains an EV-surplus variable per plugged-in `current`-type charger, gated exactly like existing sinks (pre-computed excess-PV flag AND battery SoC ≥ threshold) and rewarded so the solver prefers it over export per the configured priority. Executor side: during EV-surplus slots the executor tracks *measured* surplus in real time (clouds make 15-min forecasts unreliable) and modulates the charge current each tick, reusing the ampere actuation path, 6 A floor, and anti-flap machinery from `universal-load-balancing`. The load balancer's fuse cap always wins over surplus tracking.
- **New: commanded 1↔3-phase switching.** For chargers with a configured phase-mode entity, Darkstar selects 1-phase when the available/target charging power is below the 3-phase minimum and 3-phase above it, with hysteresis and a minimum dwell time between switches (contactor protection). Applies to EV charging generally but is primarily driven by surplus mode; binary chargers and chargers without a phase-mode entity are unaffected.
- **Settings UI:** the Excess PV Dispatch section becomes a priority-list editor (reorder sinks, enable/disable each, per-sink fields as today) plus the new EV sink options and phase-switching settings.
- **Unchanged:** water heater boost and custom entity remain slot-based (planner-scheduled, executor-toggled) exactly as today; battery-first gating (`soc_threshold_percent`), the excess-PV coarse filter, and the reward-vs-export economics model are preserved.
- **Depends on:** the `universal-load-balancing` change (EV `type: current` config, ampere setpoint actuation, anti-flap keys, balancer cap). This change must land after it.

## Capabilities

### New Capabilities

- `ev-surplus-charging`: EV as an excess-PV sink — MILP surplus variable and gating on the planner side; real-time measured-surplus tracking, amp modulation, pause/resume, and coordination with the fuse balancer on the executor side.
- `ev-phase-switching`: commanded 1↔3-phase mode selection for current-type chargers — power thresholds, hysteresis, minimum dwell time, phase-count-aware kW↔A conversion, and fail-safe behavior when the phase-mode entity is unavailable.

### Modified Capabilities

- `excess-pv-planner-dispatch`: single-sink dispatch becomes priority-ordered multi-sink dispatch; solver allocates surplus to sinks in configured order; EV joins water heater boost and custom entity as a schedulable sink; schedule output gains EV-surplus fields.
- `excess-pv-settings`: sink selector becomes an ordered priority-list editor; new EV sink configuration and phase-switching settings; config persistence moves from `excess_pv.sink` to the priority array (with migration).

## Impact

- **Planner** (`planner/solver/kepler.py`, `planner/solver/types.py`, `planner/solver/adapter.py`, `planner/pipeline.py`, `planner/output/formatter.py`): new EV-surplus solver variables, priority-aware rewards, config plumbing, schedule output fields.
- **Executor** (`executor/engine.py`, `executor/config.py`, `executor/actions.py`): priority-array config parsing, EV surplus-tracking control path, phase-mode actuation with dwell/hysteresis, interaction with the balancer cap from `universal-load-balancing`.
- **Config & migration** (`config.default.yaml`, `backend/config_migration.py`, `backend/api/routers/config.py`): `excess_pv.sink` → `excess_pv.priority[]` migration, new EV-sink and phase-switching keys, validation.
- **Frontend**: Excess PV Dispatch settings section rework (priority list editor, per-sink panels, phase-switching fields).
- **Database/schedule format**: new per-slot fields for EV surplus (additive; no migration of historical data).
- **Hardware/HA dependency**: phase switching requires the charger's phase-mode entity in HA (go-e exposes one via the MQTT integration); entity IDs are configured, never hardcoded. Users without it simply keep fixed-phase charging.
