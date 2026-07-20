## Why

The Settings "Load Balancing" tab is gated behind `system.has_ev_charger` (`frontend/src/pages/settings/index.tsx:45-50`), a leftover from when the feature (`b96f58c2`, 2026-07-06) only controlled EV chargers. It was since generalized to a unified give-way list that also sheds non-EV loads (water heater, custom entities) with no EV charger required at all — but the tab gate was never revisited. Any system without an EV charger (e.g. a battery + water heater install) can never see or enable load balancing, even though it's fully supported.

## What Changes

- Remove the `showIf: 'system.has_ev_charger'` gate from the Load Balancing tab entry — the tab is always visible, like System/Parameters/UI.
- Add an empty/explanatory state inside `LoadBalancingTab.tsx` for when there is nothing eligible to balance yet (no `type: current` EV charger and no shed-capable device configured), stating what's needed to use the feature, instead of silently hiding the whole tab.

## Capabilities

### Modified Capabilities
- `load-balancing-settings`: the Settings UI section requirement changes from "tab shown only if `has_ev_charger`" (implicit, code-only) to "tab always shown; explains prerequisites inline when nothing is configured to balance yet."

## Impact

- `frontend/src/pages/settings/index.tsx` — drop the tab's `showIf`.
- `frontend/src/pages/settings/LoadBalancingTab.tsx` — add empty-state messaging.
- No backend changes; `load_balancing.enabled` validation and behavior are unaffected.
