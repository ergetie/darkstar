# Proposal: settings-ui-quick-wins

## Why

Three small, decided settings-page improvements batched into one change (same code area, one visual verification pass): (1) the working "send test notification" capability that exists on the Executor page is invisible where users actually configure notifications — the Settings UI tab; (2) the unsaved-changes dialog says changes exist but not *which*, so users discard blind; (3) the "Water" settings tab under-sells what per-device water scheduling already supports (multiple heating sources configured as heater devices) — user decided 2026-07-13 to rename it "Heating".

## What Changes

- **Notification test button (reuse, not rebuild):** a "Send Test Notification" button in the Settings UI tab's Notifications section, calling the EXISTING backend endpoint `POST /api/executor/notifications/test` (`backend/api/routers/executor.py:530-550`) — the same one the Executor page's button uses. No new backend code. The fetch wrapper gets one shared home in `lib/api.ts`, used by both pages.
- **Unsaved-changes diff preview:** the `NavigationBlockerDialog` gains a compact list of the changed fields (label + old → new value), computed by a new pure, unit-tested helper in `settings/utils.ts` that reuses the existing form-diff machinery (`getDeepValue`/`parseFieldInput`). Both dialog call sites (`AdvancedTab`, `ParametersTab`) pass it.
- **Tab rename:** settings tab label "Water" → **"Heating"** (`frontend/src/pages/settings/index.tsx:42`). Tab `id: 'water'` and all config keys stay unchanged (routing/localStorage/config compatibility); adjacent labels reviewed for consistency.

## Capabilities

### New Capabilities

- `settings-ux`: settings-page usability behaviors — notification test access, unsaved-changes visibility, heating tab naming.

### Modified Capabilities

_None._

## Impact

- **Frontend only:** `frontend/src/lib/api.ts` (one added method), `frontend/src/pages/settings/UITab.tsx`, `components/NavigationBlockerDialog.tsx`, `settings/utils.ts` (+ its test file), `AdvancedTab.tsx`, `ParametersTab.tsx`, `settings/index.tsx`, `pages/Executor.tsx` (points its existing button at the shared api method — behavior unchanged), possibly `settings/types.ts` label review.
- **No backend, config, or API changes.** Tab id and config paths untouched.
- **Sequencing:** touches `lib/api.ts`, which `ev-dashboard-typing` also modifies — implement those two sequentially (either order), not in parallel.
