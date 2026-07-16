# Tasks: settings-ui-quick-wins

## 1. Shared API method + notification test button

- [x] 1.1 Add `testNotification(): Promise<{status: string; message: string}>` to the executor namespace in `frontend/src/lib/api.ts`, POSTing to `api/executor/notifications/test` (endpoint exists at `backend/api/routers/executor.py:530-550` — NO backend changes)
- [x] 1.2 Point `Executor.tsx`'s existing local wrapper (`executorApi.notifications.test`, ~lines 206-222) at the new shared method; `handleTestNotification` (:515) and the button (:1574-1590) stay behaviorally identical
- [x] 1.3 In `frontend/src/pages/settings/UITab.tsx`, render a "Send Test Notification" button visually associated with the HA Notify Service field in the Notifications section (see design D2 — button logic lives in the tab component, NOT in the `types.ts` field schema); local state: busy spinner while in flight, success/error feedback showing the returned message, button disabled while busy (copy the UX from the Executor implementation)

## 2. Unsaved-changes diff preview

- [x] 2.1 Add exported `listChangedFields(original, form, fields): ChangedField[]` to `frontend/src/pages/settings/utils.ts` with `ChangedField = {key: string; label: string; oldValue: string; newValue: string}`; mirror `buildPatch`'s comparison semantics (same `parseFieldInput`/`getDeepValue` usage, same companion-key handling, skip `path.length === 0` virtual fields); stringify values for display (booleans as on/off, unset as "—")
- [x] 2.2 Unit tests next to the existing `__tests__/utils.test.ts`: (a) two edited fields → two entries with correct labels/old/new, (b) untouched form → empty list, (c) agreement property: `listChangedFields` non-empty ⇔ `buildPatch` non-empty for the same inputs, (d) companion-key change is represented
- [x] 2.3 Extend `components/NavigationBlockerDialog.tsx` with optional `changes?: ChangedField[]`: render a compact scroll-capped list (label + old → new per row) between the warning text and the buttons; omitted/empty prop → exactly today's rendering
- [x] 2.4 Pass `listChangedFields(config, form, fields)` from both call sites: `AdvancedTab.tsx` (~line 208) and `ParametersTab.tsx` (~line 156)

## 3. Tab rename

- [x] 3.1 `frontend/src/pages/settings/index.tsx:42`: change `label: 'Water'` to `label: 'Heating'`; DO NOT change `id: 'water'`, the icon, or `showIf: 'system.has_water_heater'`
- [x] 3.2 Review adjacent labels for consistency with bias to keep (design D5): "Water Heaters" group header (`settings/types.ts:1071`) and GiveWayListEditor's "Water Heater" device label (:44) stay unless they now read as contradictory in the UI; record the judgment in the change notes

## 4. Verification

- [x] 4.1 `pnpm test` (all existing + new tests green), `pnpm build`, `pnpm lint` clean
- [x] 4.2 Visual check — settings UI tab: Heating tab label shows; test button sends; busy/success/error states render; Executor page test button still works (user-verified; test-notification delivery was separately traced to shadow mode on the dev machine, not a code issue)
- [x] 4.3 Visual check — diff preview: edit fields, trigger navigation, confirm the dialog lists the exact changes; confirm an unedited form still allows silent navigation (no dialog) (user-verified; also caught and fixed a gap where 7 of 9 settings tabs, including `UITab.tsx`, weren't wired to pass `changes`)
- [x] 4.4 Shared-code rule: `lib/api.ts` was touched — smoke-check dashboard and executor pages load and update normally (user-verified)
