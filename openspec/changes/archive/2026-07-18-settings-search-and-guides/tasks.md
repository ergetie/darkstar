# Tasks: Settings Search and Guides

## 1. Search Index

- [x] 1.1 Create `frontend/src/pages/settings/search/index.ts`: flatten all `*Sections` arrays from `types.ts` into search entries `{ tabId, tabLabel, sectionTitle, fieldKey, label, helper, helpText }`, merging help text from `config-help.json` by field key
- [x] 1.2 Implement the search function: case-insensitive token matching over label, key, and help text, ranked label > key > help text; unit tests covering match/rank/empty cases and the "new field is indexed automatically" property (index size equals total field count across sections)

## 2. Guide Content

- [x] 2.1 Create `frontend/src/pages/settings/search/guides.ts` with the guide data shape `{ id, title, summary, body, relatedFieldKeys }`
- [x] 2.2 Write the five initial guides in plain, non-technical language: Load Balancing, EV Charging, Water Heater, Battery/S-Index, Solar Forecast — each explaining what the function does, how its main settings affect behavior, with valid `relatedFieldKeys`
- [x] 2.3 Extend the search function to match guides (title + body) and return them as a separate group; test that all five guides are discoverable by topic name

## 3. Search UI

- [x] 3.1 Add the search box component at the top of the Settings page (`settings/index.tsx`), visible on all tabs
- [x] 3.2 Build the results dropdown panel: "Settings" and "Guides" groups, help text inline in field results, explicit empty state, keyboard navigation (arrows/Enter/Escape), close on outside click
- [x] 3.3 Show disabled/hidden hints on field results: evaluate `shouldRenderField` against the current form/config and render "requires X" / "advanced mode required" hints for fields whose conditions fail
- [x] 3.4 Build the guide viewer (modal/panel) rendering guide content with related-field links as clickable chips

## 4. Jump-to-Field

- [x] 4.1 Add a `data-field-key` anchor attribute (and a transient highlight style) to `SettingsField.tsx`
- [x] 4.2 Implement jump-to-field: set the `tab` URL param via the existing navigation path (unsaved-changes guard must fire exactly as on manual tab switch), then scroll to the anchor after the tab renders and apply the highlight; no-op safely when the anchor is absent (hidden field)
- [x] 4.3 Wire field results and guide related-field chips to the jump action; guide viewer closes before jumping

## 5. Verification

- [x] 5.1 Run frontend tests, lint, and typecheck
- [x] 5.2 Visually verify search on the Settings page: cross-tab field search, help text in results, hidden-field hints, guide open + related-field jump, unsaved-changes dialog on jump with dirty form
- [x] 5.3 `SettingsField.tsx` is shared: visually check every settings tab (System, Solar, Battery, EV, Water, Load Balancing, UI, Advanced) renders correctly
- [x] 5.4 Review guide texts with the user (content accuracy + plain language)
