# Proposal

## Why

Two silent failure classes still reach users without any warning, and one safety net is dead.

- A Fronius GEN24 user (GitHub #8) had `storage_control_mode` revert from "Charge from Grid" to "Discharge Limit" 20 s to 17 min after each write, with no Home Assistant context. The executor quietly rewrote the mode every tick, so nothing surfaced. The same silent repair can happen on any other discrete entity Darkstar writes (Deye `grid_charging_enable`, Sungrow `forced_charge_discharge_cmd`), so detection covers every select and switch the profile mode actions write, not only `work_mode`.
- `HealthChecker.check_executor` in `backend/health.py` imports `get_executor_health` from the executor router. That function was turned into the `/api/executor/health` route in 92e8960b and the import now fails; the broad `except Exception` swallows it at debug level, so "executor should be running but is not" and "last run failed" never reach the health banner.
- `s_index.base_factor` has no save validation: a value below 1.0 (which shrinks the load margin) or above `s_index.max_factor` is accepted silently.

The power-mismatch half of the original backlog item already shipped in 3a837dd7 (battery under-delivery warning). The settings-sanity idea (PV confidence, capacity and efficiency checks, Settings hint) is dropped: it is already covered by the Learned Parameters section, by `capacity_change_warning` in `backend/learning/battery_warnings.py` and by the PV site-sanity notice in `backend/learning/pv_site_sanity.py`.

## What Changes

- Detect when an inverter discrete entity (select or switch written by the profile mode actions) leaves the value Darkstar last wrote and verified, count events per entity, and raise a snoozable health warning (and an optional notification) when they recur on the same entity. Detection only: write behaviour is unchanged. Numeric entities (currents, SoC targets, power limits) are excluded because inverters round or clamp them.
- Keep the toggle `executor.notifications.on_inverter_mode_revert` (default true), following the `on_ev_soc_stale` / `on_learned_parameter_change` pattern.
- Make `HealthChecker.check_executor` work against the real executor (`ExecutorEngine` thread and status) and add a regression test that fails if the import or the status contract breaks again.
- Add an `s_index.base_factor` range warning (below 1.0 or above `s_index.max_factor`) to the existing `_validate_config_for_save` in `backend/api/routers/config.py`, following its warning pattern. It is a save warning, not a health warning.
- docs/BACKLOG.md: remove the items "[Executor] Detect Inverter Mode Reverts And Power Mismatch" and "[Settings] Warn About Out-Of-Range And Learning-Contradicted Settings" (docs/ edit approved by the user). The settings item is closed as already covered.

No DB schema change, no new dependency. The revert tracker persists through the existing `system_state` key/value table.

## Capabilities

### New Capabilities
- `inverter-revert-warning`: per-entity detection of discrete inverter entities leaving their last verified command, debounce, manual-override respect, health warning, notification toggle.
- `executor-health-check`: the health banner reports a dead executor thread or a failed last run from the real executor status.
- `s-index-base-factor-validation`: save-time warning for an out-of-range `s_index.base_factor`.

### Modified Capabilities

(none: existing health, snooze and config-save validation requirements are reused unchanged)

## Impact

- `executor/actions.py` (per-entity last verified command, deviation events), `executor/engine.py` (feed events, clear baselines when writes are suspended, persist notice), `executor/config.py`, `config.default.yaml`, `backend/api/routers/executor.py` (notifications GET/PUT, plus a read-only accessor for the health check), `backend/monitors.py` or `backend/health.py` (surface warning), `backend/health.py` (`check_executor`), `backend/api/routers/config.py` (`_validate_config_for_save`).
- Frontend: `Executor.tsx` and `pages/settings/types.ts` (toggle), `search/guides.ts`, `lib/types.ts`.
- Tests under `tests/` and `frontend/src`. docs/BACKLOG.md. No schema migration.
