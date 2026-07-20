## 1. Tab navigation

- [x] 1.1 Remove `showIf: 'system.has_ev_charger'` from the `load-balancing` entry in `ALL_TABS` (`frontend/src/pages/settings/index.tsx:45-50`) so the tab is always shown.

## 2. Empty-state messaging

- [x] 2.1 ~~In `LoadBalancingTab.tsx`, derive whether any give-way member is possible~~ — superseded: `GiveWayListEditor.tsx` (rendered inside the tab's "Give-Way Order" section, which is never `isAdvanced`-gated) already computes this reactively as `entries.length === 0` (no `type: current` charger and no `load_balancing.loads[]` entry), so no new derivation logic was needed in `LoadBalancingTab.tsx`.
- [x] 2.2 Clarified the existing empty-state copy (`GiveWayListEditor.tsx:345-352`) to explicitly name water heater/custom entity as options, not just "an on/off load", so it reads correctly for a system with no EV charger. Enable toggle, fuse rating, and sensor fields are separate fields in other sections and were never disabled by this state.
- [x] 2.3 Already satisfied: `entries` is derived live from `loadsValue`/`orderValue` props each render, so the message disappears the moment a qualifying entry is added, before saving.

## 3. Verification

- [x] 3.1 Added two tests to `GiveWayListEditor.test.tsx`: empty-state message text appears with no `type: current` charger and no loads; message disappears once a load exists even with zero EV chargers configured. Full file: 12/12 passing.
- [x] 3.2 Verified in the running dev app (Playwright against the live dev server) with `system.has_ev_charger` temporarily flipped to `false`: the Load Balancing tab appeared in the nav, was clickable, and rendered its sections correctly (screenshot captured) with no console errors related to this change. Config reverted afterward.
