## Why

`universal-load-balancing` hard-required per-phase **current** sensors (`input_sensors.grid_current_l1/l2/l3`) for real-time fuse protection. Many inverters (including the user's) only expose per-phase **power**, not current, which blocks the feature entirely for those installs even though `I = P / V` makes the conversion trivial. Separately, working through this gap surfaced two related, pre-existing UX/architecture problems in the same settings surface: the "Balanced Loads" picker lets a user select a `type: current` EV charger for on/off shedding even though that charger is silently ignored there (it's already throttled continuously by a completely separate, non-configurable mechanism), and there is no way to prioritize between multiple dynamically-throttled EV chargers sharing a phase. All three are fixed together per explicit user direction, to avoid another round of lagging follow-up changes on the same tab.

## What Changes

- Per-phase grid sensors (`input_sensors.grid_current_l1/l2/l3`) accept either a current sensor (A) or a power sensor (W/kW), auto-detected from the entity's `unit_of_measurement`/`device_class` — no manual mode toggle. The field label and settings UI reflect this ("Grid Current/Power sensor — Lx").
- W and kW power readings are normalized to a common unit before conversion; an entity whose unit cannot be recognized as current or power is a startup validation error, not a silent guess.
- New optional per-phase voltage entities (`input_sensors.grid_voltage_l1/l2/l3`) used to convert power to current (`I = P / V`) when a phase resolves to power mode. Shown as one group of 3 fields together in the settings UI whenever any phase is power-mode (not popped in per-phase independently).
- New configurable nominal fallback voltage (`load_balancing.nominal_voltage_v`, default 220 — deliberately biased low vs. the 230V nominal, since fixed voltage under-reports current during a sag, which is the wrong direction for a fuse-protection feature). Used only when a phase has no voltage entity configured at all.
- A phase with a configured voltage entity that goes stale/unavailable does **not** fall back to the nominal voltage — it feeds into the existing stale-sensor fail-safe (force to `min_current_a`, then pause) exactly like a stale current/power reading does today, using the older of the phase's readings' timestamps.
- **BREAKING (behavioral, not config-breaking)**: the "Balanced Loads" list no longer accepts `type: current` EV chargers (the picker only offers `type: binary` chargers, water heaters, and custom entities, matching what actually works). Startup validation rejects a `loads[]` entry referencing a `type: current` charger with an actionable error pointing at the new dynamically-throttled group instead.
- The Load Balancing settings tab's Balanced Loads section is restructured into two explicitly labeled groups instead of one flat list:
  - **Dynamically Throttled Chargers** — every `type: current` EV charger, always included automatically (not an add/remove list), showing its name and configured phases (read-only, sourced from the EV Chargers tab) plus a new editable **priority** field used only to rank chargers against each other when they share an overloaded phase. Lower priority number throttles toward its floor first, consistent with the existing shed-list convention.
  - **Shed as Last Resort** — the existing on/off list (water heater, custom entity, binary-type EV chargers), unchanged mechanism, relabeled to state explicitly that it only activates once every charger in the group above is at floor or paused.
- The live balancer status view (status card + REST/WebSocket payload) shows a named row per dynamically-throttled charger (state, setpoint vs. planned target) instead of a single unnamed "limited"/"paused" line that can't distinguish between multiple chargers.

Explicitly out of scope (see additions to `docs/BACKLOG.md`):
- A fully unified single priority list interleaving continuous-throttle and on/off-shed loads (deferred as "Future Ideas" — bigger rewrite of the tick-loop give-way order).
- Power/current ambiguity on the EV charger's own actuation entity (`current_entity`) — only the grid measurement sensors are in scope here.

## Capabilities

### New Capabilities

(none — this extends existing capabilities)

### Modified Capabilities

- `phase-load-balancing`: "Per-phase headroom computation" gains power+voltage sensor support and unit normalization; new requirement for per-charger priority ordering among dynamically-throttled chargers; "Stale sensor fail-safe" extended to cover per-phase voltage sensor staleness.
- `load-balancing-settings`: configuration schema gains optional per-phase voltage entities and a nominal fallback voltage; startup validation updated for the new sensor modes and for rejecting `type: current` chargers from the shed list; settings UI section restructured into the two labeled groups; live status surface extended to per-charger detail.

## Impact

- **Config schema**: `input_sensors.grid_current_l1/l2/l3` semantics widen (still valid as-is, backward compatible); new `input_sensors.grid_voltage_l1/l2/l3` (optional); new `load_balancing.nominal_voltage_v` (default 220); `load_balancing.loads[]` validation tightens (rejects `type: current` EV charger references).
- **Backend**: `executor/engine.py` phase-sensor gathering (unit detection, W/kW normalization, voltage lookup, staleness comparison across two sensors), `executor/load_balancer.py` (priority ordering within the dynamically-throttled group), `backend/api/routers/config.py` (validation rules), live status endpoint/WebSocket payload (per-charger detail).
- **Frontend**: `frontend/src/pages/settings/types.ts` (field definitions), `frontend/src/pages/settings/components/BalancedLoadsEditor.tsx` (two-group restructure, priority field for throttled chargers, conditional voltage fields), `frontend/src/components/LoadBalancerStatusCard.tsx` (per-charger status rows).
- **No breaking config changes** for existing users — a config with only `grid_current_l1/2/3` set continues to work identically. The only behavioral break is that a `type: current` charger previously (harmlessly, silently) listable in `load_balancing.loads[]` is no longer accepted there.
