# Design: Settings Search and Guides

## Context

The Settings page (`frontend/src/pages/settings/index.tsx`) renders one tab at a time, selected via the `tab` URL search param (`system`, `solar`, `battery`, `ev`, `water`, `loadbalancing` etc., plus `advanced` gated behind `advancedMode`). Every field is declared as data: per-tab `SettingsSection[]` arrays in `frontend/src/pages/settings/types.ts` (`systemSections`, `solarSections`, `batterySections`, `evSections`, `waterSections`, `loadBalancingSections`, `parameterSections`, `uiSections`, `advancedSections`), each field a `BaseField` with `key`, `label`, `helper`, `type`, and visibility conditions (`showIf` / `showIfAll` / `showIfAny`). Help text lives in `frontend/src/config-help.json` (~129 entries keyed by field key) and is currently only surfaced as hover tooltips via `SettingsField.tsx`.

One caveat: `SystemTab.tsx` mutates/extends its sections at render time from the active profile (dynamic HA control-entity fields). The static index therefore cannot know these dynamic fields.

## Goals / Non-Goals

**Goals:**
- One search box at the top of the Settings page that finds any settings field across all tabs and jumps to it.
- Show existing help text inline in results — no new per-field content to maintain.
- A small hand-written guide library (5 guides) searchable from the same box, each guide linking to its related fields.
- New fields become searchable automatically because the index is derived from the section arrays.

**Non-Goals:**
- Global Ctrl+K command palette or search on other pages.
- Searching runtime values (entity IDs, current settings values) — labels, keys, help text, and guide text only.
- Indexing SystemTab's profile-driven dynamic fields (the static "Required HA Control Entities" area is still findable via its section; dynamic per-profile fields are not individually indexed).
- Guide expansion beyond the initial 5 (separate backlog item).

## Decisions

1. **Index built at module load from the existing section arrays.** A new module (e.g. `settings/search/index.ts`) imports all `*Sections` arrays from `types.ts`, flattens them into `{ tabId, tabLabel, sectionTitle, fieldKey, label, helper, helpText }` entries (merging `config-help.json` by key), and exposes a search function. No build step, no duplicate list to maintain. Alternative considered: a hand-maintained registry — rejected, drifts out of sync.

2. **Plain substring/token matching, no library.** ~130 fields + 5 guides is tiny; case-insensitive token match over label + key + help text, ranked (label match > key match > help-text match). Alternative: fuzzy-search dependency (fuse.js) — rejected as an unnecessary dependency at this scale; can be revisited when guides grow.

3. **Results panel as a dropdown under the search box,** grouped into "Settings" and "Guides" sections, keyboard-navigable (arrows + Enter), closed on Escape/outside click. This is the "bigger box" from the discussion — an overlay panel, not a page.

4. **Jump-to-field = set `tab` search param + scroll + transient highlight.** Selecting a result sets the existing `tab` URL param, then scrolls to the field and applies a brief highlight animation. Fields get a stable DOM anchor (e.g. `data-field-key={field.key}` rendered by `SettingsField.tsx`) so the scroll target is found generically. Scroll must wait for the tab render (effect keyed on a pending-jump state).

5. **Hidden/disabled fields stay in the index and in results.** A result for a field whose `showIf` conditions currently fail is shown with a "currently disabled" hint (reusing `shouldRenderField` from `settings/logic.ts` to evaluate). Jumping still switches to the tab; if the field is not rendered at all, the result's hint explains why (e.g. "enabled when a water heater is configured") instead of a dead jump. Advanced-tab fields shown while `advancedMode` is off get an "Advanced mode required" hint.

6. **Guides are a static content module** (e.g. `settings/search/guides.ts`): array of `{ id, title, summary, body, relatedFieldKeys }`. Selecting a guide result opens a modal/expanded panel rendering the guide; related fields are rendered as clickable chips that perform the same jump-to-field action. Initial 5 guides: Load Balancing, EV Charging, Water Heater, Battery/S-Index, Solar Forecast. Content written in plain language for non-technical users.

7. **Unsaved-changes safety:** jumping between tabs must go through the same navigation path the tab bar uses, so the existing unsaved-changes guard (`useUnsavedChangesGuard` / `NavigationBlockerDialog`) keeps working. The search feature must not introduce a bypass around it.

## Risks / Trade-offs

- [`SettingsField.tsx` is shared by every tab] → Keep its change minimal (a `data-field-key` attribute + optional highlight class). Per the backlog verification rule, visually check **all** settings tabs after the change.
- [Help text missing for some fields] → Fall back to `field.helper`, else show the result without help text; never block a field from appearing in results.
- [Scroll fires before the target tab has rendered] → Drive the jump via state + effect that runs after the tab mounts; retry/no-op safely if the anchor never appears (e.g. hidden field).
- [Guide content quality is the real product] → Content reviewed with the user during verification; guides are plain-language, not developer notes.
- [SystemTab dynamic profile fields not indexed] → Accepted; their parent section/tab is still findable. Revisit if users report missing hits.
