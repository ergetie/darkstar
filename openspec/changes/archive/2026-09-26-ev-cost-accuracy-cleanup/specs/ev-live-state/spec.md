## ADDED Requirements

### Requirement: Valid SoC readings feed a last-known SoC with age
Every valid SoC reading taken through the shared reader SHALL update a per-charger last-known SoC, together with its reading time. The live reading SHALL still return none for unreadable values. The last-known SoC SHALL be exposed separately, and consumers SHALL decide whether to carry it (see `ev-soc-staleness`).

#### Scenario: Last-known updated
- **WHEN** the reader returns SoC 62.0 at 10:00
- **THEN** the last-known SoC SHALL be 62.0 with reading time 10:00

#### Scenario: Unreadable does not overwrite
- **GIVEN** a last-known SoC of 62.0 at 10:00
- **WHEN** the SoC sensor reads `unavailable` at 10:05
- **THEN** the live reading SHALL be none
- **AND** the last-known SoC SHALL remain 62.0 at 10:00
