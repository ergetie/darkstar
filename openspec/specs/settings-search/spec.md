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
The guide library SHALL contain fourteen guides: Load Balancing, EV Charging, Water Heater, Battery/S-Index, Solar Forecast, Planner & Executor Basics, Quick Actions & Command Bar, Vacation Mode, Notifications & Alerts, AI Advisor, Excess PV Dispatch, Aurora / ML Forecasting, Arbitrage & Economics, and Getting Started / HA Connection. Each SHALL be written in plain, non-technical language, explain what the function does and how its main settings affect behavior, and reference its related settings fields. Where a new guide covers a topic previously summarized inside an existing guide (Excess PV Dispatch in Solar Forecast, economics in Battery/S-Index, vacation mode in Water Heater), the existing guide SHALL mention the dedicated guide rather than being rewritten.

#### Scenario: All fourteen guides discoverable
- **WHEN** the user searches for any of the fourteen topics by name
- **THEN** the corresponding guide appears in the Guides section

#### Scenario: New-guide field links are valid
- **WHEN** any guide lists related settings fields
- **THEN** every listed field key exists in the searchable field index (enforced by a unit test)

### Requirement: Search results include glossary entries
The search SHALL maintain a glossary of short plain-language definitions for domain jargon (at minimum: SoC, S-Index, arbitrage, give-way, curtailment, load disaggregation). Matching glossary entries SHALL appear in a distinct "Glossary" section of the results panel, after fields and guides. Selecting a glossary entry SHALL open a readable view of the definition; when the entry lists related settings fields or related guides, those SHALL be presented as links that perform the standard jump-to-field behavior or open the related guide.

#### Scenario: Jargon term is defined
- **WHEN** the user types "arbitrage"
- **THEN** the Glossary section shows the arbitrage entry, and selecting it opens the full definition

#### Scenario: Glossary entry links onward
- **WHEN** the user opens a glossary entry that references a related settings field
- **THEN** clicking the field link closes the view and runs the standard jump-to-field behavior

#### Scenario: Keyboard navigation spans all three sections
- **WHEN** results contain fields, guides, and glossary entries and the user presses ArrowDown repeatedly
- **THEN** the highlight traverses fields, then guides, then glossary entries in order, and Enter selects the highlighted item

### Requirement: Synonym aliases extend matching
Guides, glossary entries, and settings fields SHALL support an optional list of alias terms, matched with the same weight as the item's title or label. A query token that matches only an alias SHALL count as a match, combining with the existing all-tokens-must-match rule. Field aliases SHALL be maintained centrally in the search module (not on the field definitions), and every alias key SHALL refer to an existing field (enforced by a unit test).

#### Scenario: Everyday vocabulary finds the technical setting
- **WHEN** the user types "breaker"
- **THEN** the main fuse field and the Load Balancing guide appear in results even though neither contains the literal word "breaker"

#### Scenario: Alias combines with literal tokens
- **WHEN** the user types a two-word query where one token matches only an alias and the other matches the item's label or body
- **THEN** the item appears in results

#### Scenario: Non-matching queries still empty
- **WHEN** the user types a term that matches no label, key, help text, body, or alias
- **THEN** the explicit empty state is shown

### Requirement: Search index derives from field definitions
The searchable field index SHALL be derived programmatically from the existing per-tab section/field definitions and `config-help.json`, not from a separately maintained list, so that fields added to a tab later are searchable without touching the search feature.

#### Scenario: New field is searchable automatically
- **WHEN** a developer adds a new field to any tab's section definitions
- **THEN** the field appears in search results with no change to search code or a manual registry
