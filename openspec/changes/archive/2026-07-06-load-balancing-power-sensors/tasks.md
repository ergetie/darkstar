## 1. Config schema

- [x] 1.1 Add `input_sensors.grid_voltage_l1/l2/l3` (optional string entity IDs) to `executor/config.py` and `config.default.yaml` (commented out / empty by default, same pattern as `grid_current_l*`).
- [x] 1.2 Add `load_balancing.nominal_voltage_v` (float, default 220) to `executor/config.py` and `config.default.yaml`.
- [x] 1.3 Add `load_balancing.charger_priority` (dict: charger id → int priority, default empty) to `executor/config.py`.
- [x] 1.4 Update `backend/config_migration.py` if any existing migration logic touches `input_sensors`/`load_balancing` keys, to ensure new keys don't break migration of older configs.

## 2. Executor: sensor kind detection and conversion

- [x] 2.1 In `executor/engine.py`'s phase-sensor gathering (~1915-1988), read and retain `attributes.unit_of_measurement` and `attributes.device_class` from the HA state payload already fetched per phase.
- [x] 2.2 Implement a helper that classifies a unit as current (A) or power (W/kW) or unrecognized, normalizing W/kW to a common unit before use.
- [x] 2.3 For power-mode phases, read the configured voltage entity (if any) the same tick; fall back to `load_balancing.nominal_voltage_v` if unset.
- [x] 2.4 Compute `measured_grid_current_a` per phase per the detected mode (`I` directly, or `P / V`).
- [x] 2.5 Track staleness per phase as the older of its relevant readings' timestamps (single reading for current-mode; power+voltage pair for power-mode with a configured voltage entity).
- [x] 2.6 Ensure a phase with no voltage entity configured is never marked stale on account of voltage (only nominal fallback applies, no staleness concept for a constant).

## 3. Config validation

- [x] 3.1 In `backend/api/routers/config.py`, extend the per-phase sensor validation to check unit recognition (current or power) for each configured `grid_current_l*` entity; produce an actionable error naming the phase and offending unit if unrecognized.
- [x] 3.2 Add validation rejecting any `load_balancing.loads[]` entry whose `device_type == "ev_charger"` references a charger with `type: current`, with a message pointing at automatic dynamic throttling instead.
- [x] 3.3 Update the "at least one balanced load" validation to also pass when at least one `type: current` EV charger exists (no `loads[]` entry required for it).
- [x] 3.4 Validate `load_balancing.charger_priority` entries reference existing `type: current` charger ids (warn or ignore stale entries left after a charger is removed — decide and document behavior).

## 4. Balancer priority logic

- [x] 4.1 Add a `priority` field to `EVBalancerInput` in `executor/load_balancer.py`, sourced from `load_balancing.charger_priority` (default: order of appearance in `ev_chargers[]`).
- [x] 4.2 Rework the per-EV loop in `LoadBalancer.tick()` from independent-per-charger reduction to priority-ordered sequential allocation: process chargers lowest-priority-first, reduce each fully to its floor (or pause) before considering the next charger's share of any remaining phase deficit.
- [x] 4.3 Confirm single-charger households produce byte-identical decisions to the current implementation (regression safety for the common case).
- [x] 4.4 Update `executor/engine.py`'s `_control_ev_chargers`/`_gather_ev_balancer_inputs` (or equivalent) to pass each charger's resolved priority into `EVBalancerInput`.

## 5. Status / API surface

- [x] 5.1 Extend the load-balancer status payload (REST endpoint + WebSocket `live_metrics` emission) to include one named entry per dynamically-throttled charger (id/name, state, setpoint, planned target).
- [x] 5.2 Keep the existing shed-list status fields (which loads shed, reason) unchanged in shape.

## 6. Frontend: settings UI

- [x] 6.1 Extend the HA-entities endpoint/response (`Api.haEntities` and its backend source) to include `unit_of_measurement` (and `device_class` if cheaply available) per entity, so the settings UI can decide whether to reveal voltage fields.
- [x] 6.2 Update `frontend/src/pages/settings/types.ts` field labels for the three phase sensors ("Grid Current/Power sensor — Lx"), add the three optional voltage entity fields (shown as one group, conditionally, per design.md Decision 1), and add the nominal voltage number field.
- [x] 6.3 Restructure `frontend/src/pages/settings/components/BalancedLoadsEditor.tsx` (or split into two components) into "Dynamically Throttled Chargers" (auto-populated from `type: current` chargers, priority-only editable field, read-only name/phases) and "Shed as Last Resort" (existing add/remove list, now filtered to exclude `type: current` chargers from the EV charger picker).
- [x] 6.4 Add/adjust helper copy in both groups per design.md Decision 5/6 (explain the two-tier ordering explicitly).
- [x] 6.5 Wire the new fields through `useSettingsForm` save path (existing config write path, no new endpoint needed).

## 7. Frontend: live status card

- [x] 7.1 Update `frontend/src/components/LoadBalancerStatusCard.tsx` to render one row per dynamically-throttled charger (name, state, setpoint vs. planned) instead of a single generic "limited"/"paused" line.
- [x] 7.2 Keep the existing per-phase bars and shed-list summary unchanged.

## 8. Tests

- [x] 8.1 Unit tests for sensor-kind detection (current/power/unrecognized) and W/kW normalization.
- [x] 8.2 Unit tests for power→current conversion with a configured voltage entity, with nominal fallback, and with a stale configured voltage entity (asserting the existing stale-sensor fail-safe fires, not a silent nominal substitution).
- [x] 8.3 Unit tests for priority-ordered sequential allocation across 2+ dynamically-throttled chargers sharing a phase, plus a regression test confirming single-charger behavior is unchanged.
- [x] 8.4 Config validation tests: unrecognized unit, `type: current` charger rejected from `loads[]`, "at least one balanced load" satisfied by a dynamically-throttled charger alone.
- [x] 8.5 Frontend tests for `BalancedLoadsEditor`'s two-group split and the conditional voltage-fields group.
- [x] 8.6 E2E/dry-run test extending the existing `test_load_balancer_e2e_dry_run.py` pattern to cover a power-sensor-configured phase end to end.

## 9. Documentation

- [x] 9.1 Update settings UI helper text and `config.default.yaml` comments to describe the new sensor modes, voltage fallback, and two-tier balanced-loads structure.
