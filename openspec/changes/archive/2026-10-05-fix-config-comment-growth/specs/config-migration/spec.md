## ADDED Requirements

### Requirement: Template merge output is size-stable across repeated writes
The template merge SHALL take only values from the user config and SHALL take all comments from the template. Writing the same config repeatedly, through either the config save API or startup migration, MUST produce identical output, and every template comment block MUST appear exactly once.

#### Scenario: Repeated saves with a populated list key
- **WHEN** the user config has a non-empty `executor.excess_pv.priority` and the template merge runs 5 times in a row, each run using the previous output as the user config
- **THEN** every output is byte-identical to the first one, and the template's `excess_pv` example comment block appears exactly once

#### Scenario: Already-bloated config self-heals
- **WHEN** the user config contains several duplicated copies of a template comment block
- **THEN** after one template merge the output contains that block exactly once, and all user values are unchanged

#### Scenario: User values and quoting preserved
- **WHEN** the template merge runs on a user config with quoted string values and populated list keys
- **THEN** every user value appears unchanged in the output, and quoted strings keep their quote style
