## Context

`ALL_TABS` in `frontend/src/pages/settings/index.tsx` filters tabs client-side via a `showIf` string naming a `system.*` boolean flag (`has_solar`, `has_battery`, `has_water_heater`, `has_ev_charger`). The Load Balancing tab reused `has_ev_charger` when it was added, because at the time the feature only balanced EV chargers. It now also balances water heaters and arbitrary `custom_entity` loads (`load_balancing.loads[]`), and a `custom_entity` load requires no system flag at all — it's just an HA entity the user types in. So no combination of existing flags correctly predicts "can this system use load balancing."

## Goals / Non-Goals

**Goals:**
- The tab is reachable on every system, regardless of `has_ev_charger`/`has_water_heater`.
- When a system has no `type: current` EV charger and no water heater configured, the tab still renders and tells the user what's needed, instead of silently vanishing (today's failure mode this change fixes) or showing a confusing empty give-way list with no explanation.

**Non-Goals:**
- No change to `load_balancing.enabled` semantics, startup validation, or the give-way list/status card behavior — those already work standalone without an EV charger.
- Not adding a new system flag or backend field to detect "any balanceable device exists"; the empty-state condition is computed client-side from already-loaded config (`ev_chargers[]` with `type: current`, `has_water_heater`) at render time, and `custom_entity` remains available regardless, so this is advisory copy, not a hard gate.

## Decisions

- **Drop the `showIf` gate entirely** rather than widening it to `has_ev_charger || has_water_heater`: a widened flag would still hide the tab for a system whose only balanceable load is a `custom_entity` (no water heater, no EV charger) — which config already supports today. Dropping the gate matches how `system`/`parameters`/`ui` tabs behave (always shown) and is simpler than inventing a third flag.
- **Empty-state reuses the existing `GiveWayListEditor` empty state, not a new one in `LoadBalancingTab.tsx`**: `GiveWayListEditor.tsx` (rendered by the tab's "Give-Way Order" section, which is never `isAdvanced`-gated) already computes `entries` reactively from `ev_chargers[]` (`type: current`) and `load_balancing.loads[]`, and already rendered a message when `entries.length === 0` before this change. That condition is exactly "nothing to balance yet" regardless of `has_ev_charger`/`has_water_heater`, so no new derivation logic was needed — only the copy was clarified to name water heater/custom entity explicitly instead of generic "on/off load". The enable toggle, sensors, and fuse-rating fields live in separate sections and were never gated by this state.

## Risks / Trade-offs

- [Users on non-EV, non-water-heater systems (e.g. only a custom shed entity) still see a generic "you need at least one of X" message that doesn't mention custom entities explicitly] → Empty-state copy explicitly lists all three eligible options (dynamic EV charger, water heater, or a custom entity added directly in the give-way list) so it doesn't imply the tab is EV/water-heater-only.
- [Tab always appearing could look like a regression to users who expect tabs to reflect installed hardware] → Consistent with `system`/`parameters`/`ui`, which are already always-shown; low risk.
