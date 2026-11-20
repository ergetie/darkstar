## Purpose

Defines how the price feed behaves when Nordpool fetches fail, time out or return partial data, so the planner keeps usable prices and callers are not blocked.

## Requirements

### Requirement: Today's prices survive a failed tomorrow fetch
When today's prices were fetched successfully, a failed or empty tomorrow fetch SHALL NOT discard them. The price feed SHALL return today's slots, plus any tomorrow slots available from the last-good fallback.

#### Scenario: Tomorrow fetch fails after 13:00
- **WHEN** it is after 13:00, today's fetch succeeds and tomorrow's fetch raises or times out
- **THEN** the returned prices SHALL contain all of today's slots

#### Scenario: Tomorrow not yet published
- **WHEN** it is after 13:00, today's fetch succeeds and tomorrow's fetch returns no values
- **THEN** the returned prices SHALL contain all of today's slots

### Requirement: Last-good prices fill fetch failures
The system SHALL keep the last complete set of published Nordpool prices, also across restarts. When a fetch fails, the price feed SHALL fill the gap with those prices, only for slots that have not yet ended, and SHALL log a warning that stored prices are in use.

#### Scenario: Total fetch failure with stored prices
- **WHEN** both fetches fail and stored prices contain slots that have not ended
- **THEN** the price feed SHALL return those slots and no ended slot

#### Scenario: Restart during an outage
- **WHEN** the backend restarts and the fetch fails
- **THEN** the price feed SHALL still return the stored slots that have not ended

#### Scenario: Nothing usable stored
- **WHEN** the fetch fails and no stored slot has an end time in the future
- **THEN** the price feed SHALL return an empty list

#### Scenario: Stored prices do not match current settings
- **WHEN** the stored prices were saved for a different price area, currency or resolution than configured
- **THEN** they SHALL NOT be used

#### Scenario: Pricing settings changed
- **WHEN** fee, tax or markup settings change after the prices were stored
- **THEN** fallback prices SHALL be calculated with the new settings

#### Scenario: Fallback slots remain published prices
- **WHEN** slots come from stored prices
- **THEN** they SHALL carry `price_source` "nordpool"

### Requirement: Incomplete fetches are not stored as last-good
Stored prices SHALL be overwritten only after a complete fetch: today's prices, and after 13:00 also tomorrow's.

#### Scenario: Incomplete fetch keeps older storage
- **WHEN** it is after 13:00 and tomorrow's fetch returns nothing
- **THEN** the stored prices SHALL NOT be overwritten

### Requirement: Failed fetches are not retried on every call
After a failed or empty tomorrow fetch, or a total fetch failure, the price feed SHALL serve its result without refetching for 5 minutes. During a total failure the result SHALL be the stored slots that have not ended, or an empty list when there are none.

#### Scenario: Repeated calls after a failed tomorrow fetch
- **WHEN** tomorrow's fetch failed and the price feed is called again within 5 minutes
- **THEN** no new fetch SHALL be made and the same slots SHALL be returned

#### Scenario: Repeated calls during a total outage
- **WHEN** every fetch failed and the price feed is called again within 5 minutes
- **THEN** no new fetch SHALL be made and the stored slots that have not ended SHALL be returned, or an empty list if none

#### Scenario: Retry after 5 minutes
- **WHEN** the price feed is called more than 5 minutes after a failed fetch
- **THEN** it SHALL fetch again

#### Scenario: Recovery after an outage
- **WHEN** a fetch after the 5 minute window succeeds
- **THEN** the fresh prices SHALL be returned and cached normally
