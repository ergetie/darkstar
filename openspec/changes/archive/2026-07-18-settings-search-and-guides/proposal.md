# Settings Search and Guides

## Why

The settings page spans seven tabs (System, Solar, Battery, EV, Water, Load Balancing, UI, Advanced) with ~130 configuration fields. Finding a specific field (e.g. "Main Fuse") requires knowing which tab it lives on and scanning manually. The per-field help text that already exists in `config-help.json` is hidden behind hover-tooltips, and there is no in-app explanation of what the major functions actually do.

## What Changes

- Add a search box at the top of the Settings page (settings page only — no global shortcut / command palette).
- Typing opens a results panel that searches across all settings tabs:
  - **Settings results**: matching fields shown with their tab name and existing help text (from `config-help.json` / field `helper`) inline; clicking a result switches to the correct tab, scrolls to the field, and highlights it briefly.
  - **Guides results**: matching entries from a new, small library of hand-written user guides.
- Ship 5 initial guides: Load Balancing, EV Charging, Water Heater, Battery/S-Index, Solar Forecast. Each is a short plain-language explainer of what the function does and which settings drive it, with links that jump to those fields.
- The search index is derived from the existing field definitions (key, label, tab) plus help text, so new fields are searchable automatically without maintaining a separate list. Guide content is the only hand-maintained part.
- Fields hidden by the current config (e.g. EV fields with no charger configured, advanced-only fields) are still findable; the result indicates when a field is currently disabled/hidden and why, rather than silently omitting it or jumping to an invisible field.

Out of scope: global Ctrl+K palette, search on other pages, guide expansion beyond the initial 5 (tracked as a separate backlog item "Expand Settings-Search User Guides").

## Capabilities

### New Capabilities

- `settings-search`: Search box on the Settings page covering all settings fields and user guides — result matching, jump-to-field behavior, disabled-field handling, and the initial guide library.

### Modified Capabilities

<!-- None. `settings-ux` requirements are unchanged; search is additive. -->

## Impact

- **Frontend only** — no backend/API changes.
  - `frontend/src/pages/settings/index.tsx` and tab components: search box mount point, tab-switch + scroll-to-field + highlight mechanism.
  - New components: search box, results panel, guide viewer.
  - New content module: guide texts (5 entries).
  - Search index built from the existing field definitions in the settings tabs and `frontend/src/config-help.json`.
- Per backlog verification rule: settings tabs share `SettingsField.tsx`; if it is touched, all settings tabs must be visually checked.
