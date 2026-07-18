# Settings Search

## Purpose

A search box on the Settings page that finds fields across all tabs (including hidden/disabled ones) and surfaces a library of plain-language user guides, so users can locate a setting or understand a feature without knowing which tab it lives on.

## Requirements

### Requirement: Settings page has a search box covering all tabs
The Settings page SHALL display a search box at the top of the page (all tabs). Typing a query SHALL open a results panel that searches settings fields across every settings tab, regardless of which tab is currently active. The search SHALL exist only on the Settings page — no global keyboard shortcut or presence on other pages.

#### Scenario: Field on another tab is found
- **WHEN** the user is on the System tab and types "fuse" into the search box
- **THEN** the results panel lists matching fields from the Load Balancing tab (e.g. main fuse rating), each showing its tab name

#### Scenario: Matching is forgiving about case and word position
- **WHEN** the user types "FUSE" or "main fu"
- **THEN** the same field results appear as for "fuse" (case-insensitive substring/token matching over label, key, and help text)

#### Scenario: No matches
- **WHEN** the user types a query that matches nothing
- **THEN** the panel shows an explicit empty state rather than closing or showing stale results

### Requirement: Results show existing help text inline
Each field result SHALL display the field's help text (from `config-help.json`, falling back to the field's `helper`) inline in the results panel. Fields with no help text SHALL still appear in results, without a help snippet.

#### Scenario: Help text shown without hovering
- **WHEN** a field with an entry in `config-help.json` appears in the results
- **THEN** its help text is visible directly in the result item

### Requirement: Selecting a field result jumps to and highlights the field
Selecting a field result SHALL navigate to the field's tab (via the existing tab navigation, preserving the unsaved-changes guard), scroll the field into view, and apply a transient visual highlight to it. Keyboard interaction (arrow keys + Enter, Escape to close) SHALL be supported in the results panel.

#### Scenario: Jump from another tab
- **WHEN** the user selects a Load Balancing field result while on the System tab
- **THEN** the page switches to the Load Balancing tab, scrolls to that field, and briefly highlights it

#### Scenario: Unsaved changes are not bypassed
- **WHEN** the user has unsaved changes on the current tab and selects a result on another tab
- **THEN** the existing unsaved-changes protection behaves exactly as it does for a manual tab switch

### Requirement: Hidden or disabled fields are findable and explained
Fields whose visibility conditions currently fail (e.g. feature not enabled, advanced mode off) SHALL still appear in search results, marked with a hint explaining why they are currently disabled or hidden, instead of being silently omitted or producing a jump to a non-existent element.

#### Scenario: Feature-gated field
- **WHEN** the user searches for a water-heater field while no water heater is configured
- **THEN** the field appears in results with a hint that it requires a water heater to be enabled, and selecting it does not perform a broken scroll

#### Scenario: Advanced-only field
- **WHEN** the user searches for an advanced-tab field while advanced mode is off
- **THEN** the field appears with an "advanced mode required" hint

### Requirement: Search results include user guides
The results panel SHALL contain a distinct "Guides" section listing guides whose title or body matches the query. Selecting a guide SHALL open a readable guide view (panel or modal) with plain-language content. Each guide SHALL list its related settings fields as clickable links that perform the standard jump-to-field behavior.

#### Scenario: Guide found by topic
- **WHEN** the user types "load balancing"
- **THEN** the Guides section shows the Load Balancing guide, and selecting it opens the guide content

#### Scenario: Guide links to its fields
- **WHEN** the user opens a guide and clicks one of its related-field links
- **THEN** the guide view closes and the standard jump-to-field behavior runs for that field

### Requirement: Initial guide library
The guide library SHALL ship with five guides: Load Balancing, EV Charging, Water Heater, Battery/S-Index, and Solar Forecast. Each SHALL be written in plain, non-technical language, explain what the function does and how its main settings affect behavior, and reference its related settings fields.

#### Scenario: All five guides discoverable
- **WHEN** the user searches for "guide" or any of the five topics by name
- **THEN** the corresponding guide(s) appear in the Guides section

### Requirement: Search index derives from field definitions
The searchable field index SHALL be derived programmatically from the existing per-tab section/field definitions and `config-help.json`, not from a separately maintained list, so that fields added to a tab later are searchable without touching the search feature.

#### Scenario: New field is searchable automatically
- **WHEN** a developer adds a new field to any tab's section definitions
- **THEN** the field appears in search results with no change to search code or a manual registry
