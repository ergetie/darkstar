# Proposal: Universal Load Balancing + EV Current Control

## Why

The user is installing a go-e Gemini Flex EV charger (16 A, 3-phase) behind a 20 A main house fuse, with no dedicated hardware load balancer ("lastbalanserare"). Darkstar must protect the main fuse in real time by dynamically adjusting the EV charge current — and, when that is not enough, shedding other controllable loads — based on live per-phase grid currents. Today Darkstar controls the EV charger as a binary ON/OFF switch only, has no per-phase awareness, and no concept of a main fuse rating. Fuses blow per phase, so the existing total-kW limit (`system.grid.max_power_kw`) cannot serve this purpose: a single heavily loaded phase can blow a fuse while total power looks fine.

## What Changes

- **New: per-phase load balancing in the executor.** A highest-priority guard layer that runs every executor tick, computes per-phase headroom against the configured main fuse, and throttles balanced loads (EV current first, then on/off shedding in priority order) to keep every phase under the fuse limit. Includes anti-flapping protection (resume delay + resume margin) so charging does not sawtooth around the limit.
- **New: variable EV charge current control.** The executor translates planned EV charging power (kW, already delivered per slot by the planner) into an ampere setpoint written to the charger's HA number entity, replacing binary ON/OFF for chargers of type `current`. Enforces the 6 A minimum charging floor (below it, charging pauses instead). Binary chargers keep working exactly as today.
- **New config:** `system.grid.main_fuse_a` (per-phase fuse rating in ampere), per-phase grid current input sensors (L1/L2/L3), a balanced-loads array (device reference, phase assignment, priority, control type), anti-flap tuning keys, and a global load-balancing enable/disable key. All per-user configurable; `system.grid.max_power_kw` is untouched (possible deprecation is a later change).
- **Feature gating:** load balancing is only available when per-phase sensors and fuse rating are configured. Users without them keep normal EV charging (as if they had an external load balancer).
- **Executor high-frequency hardening:** the executor already supports fast ticks via `executor.interval_seconds` (production will run 5 s), but it writes an execution-log DB row every tick (~17,000 rows/day at 5 s). Per-tick logging becomes change-driven/throttled so fast ticks don't bloat the database.
- **New UI:** a load-balancing settings section (global toggle, fuse rating, balanced-loads array, anti-flap tuning) and a live status view showing per-phase load vs. fuse headroom and what the balancer is currently limiting and why.
- **Out of scope (planned as separate changes, same feature family):** Excess-PV priority dispatch including EV as a sink and 1↔3-phase mode switching (Change 2); battery-assist fuse protection (Change 3). This change must not preclude them: the EV current actuation path must be reusable by the excess-PV dispatcher, and phase-aware accounting must use the charger's actual per-phase draw (cars may charge on 1, 2, or 3 phases).

## Capabilities

### New Capabilities

- `phase-load-balancing`: real-time per-phase fuse protection in the executor — headroom computation from per-phase grid sensors, prioritized throttling/shedding of balanced loads, anti-flapping, feature gating, and high-frequency tick logging hygiene.
- `ev-current-control`: variable-current EV charger actuation — planned-kW-to-ampere translation, ampere setpoint writes via HA, 6 A minimum floor with pause/resume, phase-aware power accounting from the charger's reported per-phase draw, coexistence with binary chargers.
- `load-balancing-settings`: configuration schema/validation, settings UI, and the live per-phase status view for the load balancer.

### Modified Capabilities

- `per-device-ev-scheduling`: the `ev_chargers[]` config schema gains a functioning `current` control type (control entity, min/max current); the documented "binary only" restriction is lifted.
- `ev-charge-failure-detection`: failure detection currently assumes ON/OFF control at nominal power; it must not flag balancer throttling, reduced-current charging, or a balancer-initiated pause as a charge failure.

## Impact

- **Executor** (`executor/engine.py`, `executor/controller.py`, `executor/actions.py`, `executor/override.py`, `executor/config.py`): new balancer guard layer, EV current actuation, config parsing, throttled execution logging. Existing EV source isolation (battery must not discharge into the EV) is preserved.
- **Config** (`config.default.yaml`, `backend/config_migration.py`, config validation/API): new keys under `system.grid`, `input_sensors`, `ev_chargers[]`, and a new `load_balancing` section.
- **Backend API + frontend**: new/extended endpoints for balancer status; new settings section and live status view; per-EV live metrics already flow over the HA WebSocket.
- **Database**: execution-log write pattern changes (throttling); no schema migration expected.
- **Planner**: no behavioral change — it keeps planning EV energy per slot; the balancer only caps real-time execution.
- **Hardware/HA dependency**: requires per-phase grid current sensors at the grid connection point (user's inverter provides these every 5 s via HA) and a charger exposing an ampere number entity (go-e via MQTT integration). Entity IDs are configured, never hardcoded.
