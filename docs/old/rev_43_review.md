# Rev 43 – Settings & Configuration UI: Implementation Review

This review focuses on the completed Rev 43 work (Settings & Configuration UI), looking at how the React/TypeScript settings page, config API integration, and backend behavior line up with `config.yaml` and the Rev 43 plan.

---

## 1. System Section

**Field mapping vs config**

- The System form binds to the *current* `config.yaml` structure:
  - Battery settings now live under top-level `battery.*` keys:
    - `battery.capacity_kwh`
    - `battery.max_charge_power_kw`
    - `battery.max_discharge_power_kw`
    - `battery.min_soc_percent`
    - `battery.max_soc_percent`
    - `battery.efficiency_percent` / `battery.roundtrip_efficiency_percent` (where exposed).
  - Grid max power stays as `system.grid.max_power_kw`.
  - Learning storage is `learning.sqlite_path`.
  - Time and pricing use `nordpool.price_area`, `nordpool.resolution_minutes`, `timezone`.
- This matches `config.yaml` as it stands (`battery` block at the top level, `system.grid.max_power_kw`, etc.), and reduces the old duplication between `battery` and `system.battery`. As long as planner/backend logic also reads from these paths (which it now does), the mapping is correct.

**Diff-save behavior**

- `buildSystemPatch`:
  - Reads original values via `getDeepValue`.
  - Parses the string form from the input into numbers or strings.
  - Only writes to the patch if `parsed !== currentValue`.
  - For numeric fields, an empty string produces `null`, which is explicitly *ignored* (no write), so you can’t “unset” numeric system fields by blanking them.
- This yields minimal diffs written to `config.yaml` and avoids churn.

**Validation**

- `handleFieldChange` performs key-based validation:
  - If key includes `"percent"`:
    - Must be between 0 and 100.
  - If key includes `"power_kw"`:
    - Must be `>= 0`.
  - If key includes `"capacity_kwh"`:
    - Must be `> 0`.
  - Otherwise, just numeric vs non-numeric validation.
- This maps reasonably well to semantics:
  - Capacity and SoC bounds should not be negative.
  - Grid and battery powers should be non-negative.
- Errors are shown inline under fields, and the “Save System Settings” button refuses to proceed when any validation errors are present.

Overall, the System section: **correctly mirrors config.yaml**, applies sensible validation, and only writes minimal patches via `/api/config/save`.

---

## 2. Parameters Section (Charging, Arbitrage, Water, Learning, S-Index)

**Coverage**

The Parameters tab is broken down into sub-sections that line up with Rev 43 and the backlog:

- **Charging Strategy**
  - `charging_strategy.price_smoothing_sek_kwh`
  - `charging_strategy.block_consolidation_tolerance_sek`
  - `charging_strategy.consolidation_max_gap_slots`
  - `charging_strategy.charge_threshold_percentile`
  - `charging_strategy.cheap_price_tolerance_sek`

- **Arbitrage & Export**
  - `arbitrage.export_percentile_threshold`
  - `arbitrage.enable_peak_only_export`
  - `arbitrage.export_future_price_guard`
  - `arbitrage.future_price_guard_buffer_sek`
  - `arbitrage.export_profit_margin_sek`

- **Water Heating**
  - `water_heating.power_kw`
  - `water_heating.defer_up_to_hours`
  - `water_heating.max_blocks_per_day`
  - `water_heating.min_kwh_per_day`
  - `water_heating.schedule_future_only`

- **Learning Parameter Limits**
  - `learning.min_sample_threshold`
  - `learning.min_improvement_threshold`
  - `learning.max_daily_param_change.battery_use_margin_sek`
  - `learning.max_daily_param_change.export_profit_margin_sek`
  - `learning.max_daily_param_change.future_price_guard_buffer_sek`
  - `learning.max_daily_param_change.load_safety_margin_percent`
  - `learning.max_daily_param_change.pv_confidence_percent`
  - `learning.max_daily_param_change.s_index_base_factor`
  - `learning.max_daily_param_change.s_index_pv_deficit_weight`
  - `learning.max_daily_param_change.s_index_temp_weight`

- **S-Index Safety**
  - `s_index.mode` (`static` / `dynamic` select)
  - `s_index.base_factor`
  - `s_index.max_factor`
  - `s_index.static_factor`
  - `s_index.pv_deficit_weight`
  - `s_index.temp_weight`
  - `s_index.temp_baseline_c`
  - `s_index.temp_cold_c`
  - `s_index.days_ahead_for_sindex` (array, edited as comma-separated list)

This matches both the current `config.yaml` contents and the Learning & S-index backlog items.

**Parsing / patching**

- `buildParameterFormState`:
  - Converts booleans into `'true'` / `'false'` strings in form state.
  - Converts arrays (e.g. `days_ahead_for_sindex`) into a comma-separated string.
- `parseParameterFieldInput`:
  - Numbers: empty → `null` (ignored), otherwise `Number(...)` with NaN guarding.
  - Booleans: `'true'` → `true`, anything else → `false`.
  - Arrays: splits comma-separated string, trims, parses integers, drops non-numeric.
- `buildParameterPatch`:
  - Compares parsed values against the original `config` using:
    - Element-wise equality for arrays.
    - Simple equality for scalar fields.
  - Writes only changed values into the patch object.

**Validation**

- Similar key-based heuristics as System:
  - `*percent*` → 0–100.
  - `*sek` / `*power_kw` → `>= 0`.
  - `*kwh` → `> 0`.
- Errors are per-field and block saving until fixed.

Parameters section: **complete and conservative**, covers all required knobs, and integrates cleanly with `/api/config/save`.

---

## 3. UI Section (Theme & Dashboard Defaults)

**Theme picker**

- Uses `/api/themes` via `Api.theme()` to load:
  - `themes` (name + palette),
  - `current` theme name,
  - `accent_index`.
- Renders each theme as a card with:
  - Theme name,
  - First few palette swatches to preview.
- Accent index:
  - Bound to a numeric input (0–15).
  - Clamped in `handleAccentChange`.
- `handleApplyTheme`:
  - Calls `Api.setTheme({ theme, accent_index })` → `/api/theme`.
  - Reloads themes and config afterward to keep UI in sync.

This correctly drives the server-side theme system and keeps `ui.theme` and `ui.theme_accent_index` aligned with what `/api/themes` reports.

**Dashboard defaults**

- Config now includes:
  - `dashboard.auto_refresh_enabled`
  - `dashboard.overlay_defaults` (comma-separated string of overlay keys).
- In the UI tab:
  - `auto_refresh_enabled` is a boolean checkbox bound as a `UIField`.
  - `overlay_defaults` is treated as a special case:
    - `buildUIFormState` populates `uiForm['dashboard.overlay_defaults']` directly from `config.dashboard.overlay_defaults`.
    - The overlay pill group:
      - Normalizes the string to a deduplicated, trimmed, lower-case array.
      - Determines each pill’s active state from this array.
      - Toggles membership on click and writes the updated comma list back into `uiForm['dashboard.overlay_defaults']`.
  - `buildUIPatch`:
    - Writes `dashboard.auto_refresh_enabled` like other boolean UI fields.
    - Compares `uiForm['dashboard.overlay_defaults']` with the original `config.dashboard.overlay_defaults` and writes it into `patch.dashboard.overlay_defaults` if changed.

**Current limitations / next-step idea**

- Right now, the Dashboard React components still manage overlay visibility and auto-refresh as local state; they do not yet read `dashboard.overlay_defaults` or `auto_refresh_enabled` from `/api/config`.
- This means:
  - Settings UI correctly *persists* defaults to config.
  - Dashboard behavior is unchanged until we wire those values into `Dashboard.tsx` / `ChartCard.tsx`.

This is acceptable for Rev 43 as long as the plan acknowledges that the Dashboard needs a follow-up Rev to consume these settings.

---

## 4. Reset & Shared UX

**Reset to defaults**

- A global “Reset to Defaults” button:
  - Calls `Api.configReset()` → `/api/config/reset`.
  - On success:
    - Clears all validation error maps.
    - Calls `reloadConfig()` (re-builds forms).
    - Calls `reloadThemes()` in case UI/theme config changed.
    - Shows a success pill (“All settings reset to defaults.”).
  - On failure:
    - Shows a red error pill with the error message.
- Backend `reset_config()` copies `config.default.yaml` over `config.yaml`, which matches the intended semantics.

**Section-level saves & messaging**

- Each main section (System, Parameters, UI) has:
  - A dedicated “Save …” button using a shared accent style (`cls.accentBtn`).
  - A per-section status box that:
    - Shows green for success,
    - Red for any failures or validation issues.
- Buttons are disabled while a request is in flight, and messages reset on new input, which prevents conflicting feedback.

Overall, the shared save/reset UX is consistent and robust.

---

## 5. Backend Integration & Types

- Backend routes:
  - `/api/config` → returns current `config.yaml` as JSON.
  - `/api/config/save` → deep-merges the posted patch into current config and re-enforces Nordpool defaults.
  - `/api/config/reset` → restores `config.default.yaml`.
  - `/api/themes` & `/api/theme` → theme listing and selection, unchanged but now consumed by React.
- Frontend `Api` client:
  - `Api.config`, `Api.configSave`, `Api.configReset`, `Api.theme`, `Api.setTheme` route to these endpoints with appropriate types.
  - `ConfigResponse` retains a minimal `system?.battery?.capacity_kwh` hint, but actual usage treats the config as `{ [key: string]: any }` and reads the top-level `battery` section. This is slightly inconsistent as a type hint but doesn’t break behavior.

The backend contract is respected, and the config surface now has a single, coherent UI entry point.

---

## 6. Minor Observations / Potential Polish

- **Console logs**:
  - The overlay pill code includes `console.log` statements used during debugging. They’re benign but will clutter the console in production; consider removing or guarding them behind a debug flag in a future refinement.

- **Validation heuristics**:
  - Validation uses key-name heuristics (`includes('percent')`, `includes('sek')`, etc.). It works today, but over time it might be worth switching to explicit per-field rules in the `systemSections` / `parameterSections` metadata.

- **Dashboard consumption of new settings**:
  - As noted, `dashboard.overlay_defaults` and `dashboard.auto_refresh_enabled` are now editable and persisted, but the Dashboard doesn’t yet read them. A future Rev could:
    - Initialize Dashboard overlay state from `config.dashboard.overlay_defaults`.
    - Use `dashboard.auto_refresh_enabled` to decide whether to start the auto-refresh loop by default.

---

## 7. Summary

Rev 43’s implementation:

- Aligns the Settings UI with the real `config.yaml` structure (including learning and S-index safety).
- Provides complete, validated forms for System and Parameters, with conservative diff-only saves.
- Adds a full UI tab with theme selection (using existing backend themes) and dashboard defaults persisted via config.
- Implements a global “Reset to defaults” flow wired to `/api/config/reset`, keeping settings, themes, and forms in sync.

The remaining follow-up work is mainly about **consuming** the new dashboard defaults in the Dashboard code and cleaning up minor debug logs / validation heuristics—functionally, Rev 43 is in good shape. 

