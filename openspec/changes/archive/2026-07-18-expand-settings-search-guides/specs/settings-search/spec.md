# Settings Search — Delta: Expand Guides, Glossary, Aliases

## MODIFIED Requirements

### Requirement: Initial guide library
The guide library SHALL contain fourteen guides: Load Balancing, EV Charging, Water Heater, Battery/S-Index, Solar Forecast, Planner & Executor Basics, Quick Actions & Command Bar, Vacation Mode, Notifications & Alerts, AI Advisor, Excess PV Dispatch, Aurora / ML Forecasting, Arbitrage & Economics, and Getting Started / HA Connection. Each SHALL be written in plain, non-technical language, explain what the function does and how its main settings affect behavior, and reference its related settings fields. Where a new guide covers a topic previously summarized inside an existing guide (Excess PV Dispatch in Solar Forecast, economics in Battery/S-Index, vacation mode in Water Heater), the existing guide SHALL mention the dedicated guide rather than being rewritten.

#### Scenario: All fourteen guides discoverable
- **WHEN** the user searches for any of the fourteen topics by name
- **THEN** the corresponding guide appears in the Guides section

#### Scenario: New-guide field links are valid
- **WHEN** any guide lists related settings fields
- **THEN** every listed field key exists in the searchable field index (enforced by a unit test)

## ADDED Requirements

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
