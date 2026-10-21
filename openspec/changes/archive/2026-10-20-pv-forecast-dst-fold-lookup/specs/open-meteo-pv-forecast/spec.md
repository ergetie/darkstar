## MODIFIED Requirements

### Requirement: Efficient Live PV Slot Mapping

The live Open-Meteo forecast path SHALL map PV power to each requested slot by direct lookup on a canonical UTC instant key, so that mapping cost does not grow with the length of the fetched solar series. Both series keys and slot start times SHALL be normalized to the same canonical form (the 15-minute-floored UTC instant) before matching, so the match MUST be independent of datetime type (python `datetime`, pytz-aware, or pandas `Timestamp`), timezone representation, and DST `fold`.

#### Scenario: Slot matches a series timestamp in a different timezone
- **WHEN** a slot start is a pytz-aware or pandas Timestamp local time and the series key for the same instant is a fixed-offset aware datetime
- **THEN** the slot SHALL receive that key's summed watts converted to kWh (`watts * 0.25 / 1000`)

#### Scenario: Repeated autumn DST hour matches
- **WHEN** slots come from `dst_safe_date_range` in Europe/Stockholm covering the repeated hour (e.g. 2026-10-25 02:00–02:45 +01:00, fold=1) and the series has fixed-offset keys for those instants
- **THEN** every slot SHALL be matched, no slot SHALL be reported as estimated, the incomplete-forecast error SHALL NOT be recorded, and forecast errors SHALL be cleared

#### Scenario: Spring-forward gap matches
- **WHEN** slots span the spring-forward transition (e.g. 2026-03-29 in Europe/Stockholm) and the series covers every instant
- **THEN** every slot SHALL be matched and no slot SHALL be reported as estimated

#### Scenario: Slot has no matching series timestamp
- **WHEN** no series key equals the slot's canonical instant
- **THEN** the slot SHALL be filled from the stored-forecast fallback and counted as estimated, never defaulted to zero

#### Scenario: Long series does not slow mapping
- **WHEN** the fetched series contains thousands of historical entries before the first requested slot
- **THEN** mapping a 7-day (672-slot) request SHALL complete in well under one second and produce the same values as with only the relevant entries

## ADDED Requirements

### Requirement: Stored baseline slot matching by instant
The stored-forecast fallbacks (stored Open-Meteo baselines and the DB forecast slots) SHALL match stored rows to price slots by the same canonical UTC instant key as the live path, independent of datetime type and DST fold.

#### Scenario: Stored baseline in the repeated hour
- **WHEN** a stored baseline exists for an instant in the repeated autumn hour and the price slot for that instant is a pandas Timestamp with fold=1
- **THEN** the stored value SHALL be used as an exact match and the slot SHALL NOT be counted as estimated
