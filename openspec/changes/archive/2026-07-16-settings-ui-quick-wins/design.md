# Design: settings-ui-quick-wins

## Context

Verified 2026-07-13:

- **Existing test-notification stack (the reuse target):** backend `POST /api/executor/notifications/test` (`backend/api/routers/executor.py:530-550`) calls `executor.send_notification("Test", ...)` and returns `{status, message}`. The Executor page already has a full-UX button: local fetch wrapper `executorApi.notifications.test()` defined inside `Executor.tsx` (~lines 206-222), handler `handleTestNotification` (:515) with `testingNotification` loading state, button markup (:1574-1590). Note the wrapper lives in `Executor.tsx`, NOT in `lib/api.ts`.
- **Settings UI tab:** `UITab.tsx` renders the declarative `uiSections` from `settings/types.ts:701+`; the Notifications section's first field is `executor.notifications.service` ("HA Notify Service", types.ts:706-713). Field rendering goes through `components/SettingsField.tsx` (has a `'service'` case).
- **Unsaved-changes machinery:** `NavigationBlockerDialog.tsx` is a simple presentational modal (`visible/onStay/onLeave` props, static text). Used by exactly two call sites: `AdvancedTab.tsx:208` and `ParametersTab.tsx:156`. Both tabs already hold `config` (original), `form` (current values), and `fields` — the inputs `buildPatch` (settings/utils.ts:210) uses to compute saves. The diff-computation primitives (`getDeepValue`, `parseFieldInput`) are exported and already unit-tested (`__tests__/utils.test.ts`).
- **Tab naming:** `settings/index.tsx:42` — `{ id: 'water', label: 'Water', icon: <Droplets/>, showIf: 'system.has_water_heater' }`. Related labels: "Water Heaters" group header (types.ts:1071), GiveWayListEditor's device-type label "Water Heater" (:44).

## Goals / Non-Goals

**Goals:**
- Test button in the Settings Notifications section with the same UX quality as the Executor one (loading state, success/error feedback), sharing one API wrapper.
- The blocker dialog shows exactly which fields would be discarded, with old → new values.
- Tab reads "Heating"; nothing functional changes.

**Non-Goals:**
- No new backend endpoint or notification logic; no change to what the test notification sends.
- No renaming of `id: 'water'`, `has_water_heater`, `water_heater_devices`, or any config key — labels only.
- No redesign of the blocker dialog beyond adding the list; no change to the `UnsavedChangesBanner`.
- Device-type label "Water Heater" in GiveWayListEditor stays (the devices ARE water heaters; only the tab's scope name changes).

## Decisions

### D1: One shared API method; both buttons use it

Add `testNotification()` to the executor namespace in `lib/api.ts` (typed `{status: string, message: string}` response, matching the endpoint). The new settings button uses it; `Executor.tsx`'s local `executorApi.notifications.test` wrapper is pointed at it too (tiny dedupe, zero behavior change). Rationale: two hand-rolled fetches to one endpoint is exactly the drift this project's typing work fights.

### D2: Button rendered by `UITab.tsx`, not by extending the field schema

The declarative field schema in `types.ts` is data; wiring an async handler into it would leak behavior into config. `UITab.tsx` renders the button itself within the Notifications section (adjacent to the service field), with local loading/result state copied from the Executor implementation's UX (spinner while sending, toast/inline feedback for success/failure). If placement inside the section markup proves awkward, placing it in the section description row is acceptable — implementer's judgment, but it must be visually associated with the HA Notify Service field.

### D3: Diff list computed by a new pure helper, reusing existing primitives

New exported `listChangedFields(original, form, fields): ChangedField[]` in `settings/utils.ts` where `ChangedField = {key, label, oldValue, newValue}` (display-stringified values). It mirrors `buildPatch`'s comparison semantics (same `parseFieldInput`/`getDeepValue` machinery, same companion-field handling) but returns a flat display list instead of a nested patch. Unit tests go next to the existing `__tests__/utils.test.ts`. Rationale: the dialog needs labels and old values, which `buildPatch`'s output (a nested config patch) doesn't carry; deriving both from one shared comparison keeps them consistent.

### D4: Dialog stays dumb

`NavigationBlockerDialog` gains an optional `changes?: ChangedField[]` prop rendering a compact, scroll-capped list (e.g. max-height with overflow) between the warning text and the buttons; absent/empty prop renders exactly today's dialog. Both call sites compute `listChangedFields(...)` and pass it. Backwards-compatible prop keeps the component reusable.

### D5: Rename is label-only

`label: 'Water'` → `'Heating'` at `settings/index.tsx:42`. Review pass over "Water Heaters" section header (types.ts:1071) — keep or adjust to "Heating Devices" is implementer's judgment with a bias to KEEP (the devices are configured as water heaters; renaming headers beyond the tab was not requested). `id: 'water'` untouched.

## Risks / Trade-offs

- [Diff list drifts from buildPatch semantics] Two functions comparing form vs config could disagree → both use the same primitives; the unit tests include a case asserting `listChangedFields` is non-empty exactly when `buildPatch` produces a non-empty patch for the same inputs.
- [Long change lists blow up the modal] Scroll-capped list; the dialog stays `max-w-sm`-ish with overflow.
- [lib/api.ts merge conflict with ev-dashboard-typing] Sequential implementation noted in proposal Impact; the additions are in different regions of the file, so conflicts are mechanical.

## Migration Plan

None — frontend-only, additive. Rollback = revert.

## Open Questions

_None — tab wording decided by the user 2026-07-13 ("Heating")._

## Implementation Notes

- **3.2 label review (revised):** initial judgment was to keep "Water Heaters" (`types.ts:1071`). Live testing showed it reads as directly contradictory — it's the prominent `<h2>` heading rendered right below the "Heating" tab. Renamed to "Heating Devices". Also renamed WaterTab's "Save Water Settings" button to "Save Heating Settings" for the same reason. GiveWayListEditor's "Water Heater" device-type label (`GiveWayListEditor.tsx:44`) is unchanged — it names a specific device type inside an add/select control, not a page-level heading, so it doesn't read as contradictory.
- **2.4 scope correction:** the design's claim that `NavigationBlockerDialog` has "exactly two call sites" (`AdvancedTab.tsx`, `ParametersTab.tsx`) was wrong — verified via grep there are 9: `SystemTab`, `ParametersTab`, `SolarTab`, `BatteryTab`, `EVTab`, `WaterTab`, `LoadBalancingTab`, `UITab`, `AdvancedTab`. All 9 now pass `changes={listChangedFields(...)}`; `UITab.tsx` (where notification settings live) was the one a user hit blank first, since it was neither in the original 2 nor visibly broken until tested live.
- To keep `listChangedFields` in exact agreement with `buildPatch`'s internal comparison (`isDirty`/`save` both use the hook's dynamic `fields`, which differs from the static field-list constants for `BatteryTab`/`SystemTab` once inverter-profile entities are injected), `useSettingsForm`'s return type now exposes `fields: BaseField[]` and all 9 tabs pass that instead of their imported static field-list constant.
