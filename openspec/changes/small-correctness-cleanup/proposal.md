## Why

The stabilization review confirmed a batch of small, independent correctness defects and misleading/dead code in the executor and planner (findings #8, #12, #13, #14, #19, #20, #21, #24). Each has a bounded blast radius and needs no architecture decision — unlike the other planned changes. Grouping them into one low-risk cleanup avoids opening many tiny PRs against the same files and keeps the higher-severity changes focused.

## What Changes

- **EV charge current uses nominal voltage, not worst-case (#8).** The kW→Amps conversion currently divides by `min_voltage_v` (46 V), commanding ~4% more current than the plan intends; switch to `nominal_voltage_v` (48 V) and keep `min_voltage_v` for safety limits only.
- **Water-boost cancellation notification is actually sent (#24).** The low-SoC cancellation notice is created but never `await`ed, so it is silently dropped; await it like the other notification call sites.
- **WebSocket broadcast failures are logged, not swallowed (#13).** The real-time error/status push is wrapped in a bare `except: pass`; log at debug/warning so genuine WS faults are visible (data is already persisted first).
- **Remove the dead, broken `force_export` path (#21).** The quick action has no UI caller and hardcodes the export limit to 0 W (exports nothing). Remove the override type, controller branch, and engine handler rather than fix an unreachable path.
- **Reported plan cost uses the effective export price (#20).** The displayed `total_cost_sek` recomputes with the raw export price while the optimizer minimized using the thresholded price; align the report to what was actually optimized (decisions are unaffected — display only).
- **Simulation SoC projection reflects total battery charge and the SoC band (#12, #14).** The `/api/simulate` diagnostic curve reads a grid-only `charge_kw`, under-stating SoC when the battery charges from PV; use total battery charge and apply the parsed-but-discarded min/max SoC clamp.
- **Remove dead/misleading residue (#19, #14).** Fix the stale Kepler terminal-value comments and the duplicate `target_soc_kwh` assignment; delete the parsed-then-discarded values and the unreachable `if entity is None` branch and redundant `pass`. No behavior change.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `executor`: correct the EV charge-current conversion (#8), guarantee delivery of the boost-cancellation notification (#24), surface WebSocket broadcast failures instead of swallowing them (#13), and remove the dead/broken `force_export` quick action (#21).
- `planner`: report plan cost at the same effective (thresholded) export price the optimizer used (#20), and make the simulation SoC projection reflect total battery charge within the configured SoC band (#12).

## Impact

- **Code:** `executor/controller.py` (#8, #21), `executor/engine.py` (#13, #21, #24), `executor/actions.py` (#14), `planner/solver/kepler.py` (#19, #20), `planner/solver/adapter.py` (#20), `planner/simulation.py` (#12, #14), `planner/output/soc_target.py` (#14), `backend/ha_socket.py` (#14).
- **No config, schema, or dependency changes. No breaking changes** — `force_export` has no UI caller; the cost change is display-only; all other fixes correct existing behavior.
- **Cross-change coordination:** this change shares the `executor` spec with `harden-executor-safety` (distinct requirements — no overlap) and edits `kepler.py`, which `harden-executor-safety` (#34) and the paused `price-forecasting-module-3/4` also touch. Land this cleanup first, or coordinate, to avoid re-touching the same lines twice.
- **Pure cleanup items (#19, #14) carry no spec-level requirement change** — they are tasks only.
