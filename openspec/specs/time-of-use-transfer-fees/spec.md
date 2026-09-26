# Capability: Time-of-Use Transfer Fees

## Purpose

Lets the grid transfer fee vary by time of day, weekday and season via ordered rules (with Swedish holidays treated as weekends), applied consistently to every import price consumer, while flat mode preserves the previous behaviour.

## Requirements

### Requirement: Flat transfer fee by default
The system SHALL use `pricing.grid_transfer_fee_sek` for every slot when `pricing.transfer_fee_mode` is `flat` or absent, producing import prices identical to the previous behaviour.

#### Scenario: Existing config without new keys
- **WHEN** the config has no `transfer_fee_mode` and no `transfer_fee_rules`
- **THEN** every slot's import price equals `(spot + grid_transfer_fee_sek + energy_tax_sek) * (1 + vat_percent/100)`

#### Scenario: Rules present but mode flat
- **WHEN** `transfer_fee_mode` is `flat` and `transfer_fee_rules` contains rules
- **THEN** the rules are ignored and the flat fee is used

### Requirement: Per-slot fee from ordered rules
In `time_of_use` mode the system SHALL resolve the transfer fee per slot by evaluating `transfer_fee_rules` in order against the slot start in the configured local timezone, using the first matching rule's `fee_sek`, and falling back to `grid_transfer_fee_sek` when no rule matches.

#### Scenario: Winter weekday daytime
- **WHEN** a rule `{months:[11,12,1,2,3], weekdays:[0..4], hours:{start:6,end:22}, fee_sek:0.76}` exists and the slot starts Tue 2026-12-01 10:00 local
- **THEN** the transfer fee is 0.76

#### Scenario: No rule matches
- **WHEN** the same rule exists and the slot starts Tue 2026-12-01 23:00 local
- **THEN** the transfer fee is `grid_transfer_fee_sek`

#### Scenario: First match wins
- **WHEN** two rules both match a slot
- **THEN** the fee of the earlier rule in the list is used

#### Scenario: Omitted fields match all
- **WHEN** a rule omits `months`, `weekdays` and `hours`
- **THEN** it matches every slot

### Requirement: Hour ranges
A rule's `hours` SHALL be a half-open local-hour range `[start, end)` with `0 <= start <= 23`, `1 <= end <= 24`, `start != end`; when `start > end` the range SHALL wrap past midnight.

#### Scenario: Wrapping night range
- **WHEN** a rule has `hours:{start:22,end:6}`
- **THEN** slots starting 22:00–05:45 match and a slot starting 06:00 does not

#### Scenario: End of range is exclusive
- **WHEN** a rule has `hours:{start:6,end:22}`
- **THEN** a slot starting 21:45 matches and a slot starting 22:00 does not

### Requirement: Swedish holidays as weekend
When `pricing.holidays_as_weekend` is true, the system SHALL treat Swedish public holidays and the eves Midsommarafton, Julafton and Nyårsafton as weekend days for weekday matching; when false or absent, holidays SHALL match as their actual weekday.

#### Scenario: Holiday toggle on
- **WHEN** the toggle is on and a Mon–Fri daytime rule exists and the slot starts Fri 2026-12-25 10:00
- **THEN** the Mon–Fri rule does not match and a rule including Saturday or Sunday may match

#### Scenario: Holiday toggle off
- **WHEN** the toggle is off and the slot starts Fri 2026-12-25 10:00
- **THEN** the Mon–Fri rule matches

#### Scenario: Moving holidays computed
- **WHEN** holidays are computed for 2027
- **THEN** Långfredagen is 2027-03-26, Annandag påsk 2027-03-29 and Midsommardagen 2027-06-26

### Requirement: All price consumers use the per-slot fee
Import prices for Nordpool slots, price-forecast slots and EV post-horizon slots SHALL all use the fee resolved for that slot's start time. Energy tax and VAT SHALL remain flat.

#### Scenario: Forecast slots
- **WHEN** price forecasts are derived for a slot inside a higher-fee window
- **THEN** its import p10/p50/p90 include that window's fee

### Requirement: Historical prices unchanged
Changing fee rules SHALL NOT alter import prices already recorded for past slots.

#### Scenario: Rules edited
- **WHEN** a user edits rules after slots have been recorded
- **THEN** stored `slot_observations.import_price_sek_kwh` values are unchanged

### Requirement: Rule validation
Config save SHALL return an error for a rule with months outside 1–12, weekdays outside 0–6, an invalid hour range, or a missing/negative/non-numeric `fee_sek`, and a warning when mode is `time_of_use` with no rules. At runtime an invalid rule SHALL be skipped with a logged warning and never abort price calculation.

#### Scenario: Invalid hour range rejected
- **WHEN** a user saves a rule with `hours:{start:8,end:8}`
- **THEN** the save returns a validation error naming the rule

#### Scenario: Runtime tolerance
- **WHEN** config on disk contains an invalid rule
- **THEN** prices are still produced, the invalid rule is skipped and a warning is logged

### Requirement: Settings editor
Settings → System → "Pricing & Timezone" SHALL provide a Flat / Time-of-use toggle; in Time-of-use mode an editable, reorderable rule table (months, weekdays, hour range, fee), a fixed non-deletable last row "All other times" bound to `grid_transfer_fee_sek`, the holiday toggle, and a 24-hour fee preview for a selectable date.

#### Scenario: Switching back to flat keeps rules
- **WHEN** a user switches from Time-of-use to Flat and saves
- **THEN** `transfer_fee_rules` is preserved in config and restored when switching back

#### Scenario: Preview reflects rules
- **WHEN** a user edits rules and picks a date
- **THEN** the preview shows the fee per hour for that date using the same matching semantics as the backend, including holidays when the toggle is on

#### Scenario: Preview updates on unsaved edits
- **WHEN** a user changes a rule (fee, hours, months, weekdays), the mode, the "All other times" fee or the holiday toggle, without saving and without changing the preview date
- **THEN** the preview immediately shows the fees for the current, unsaved values

#### Scenario: Preview hour details
- **WHEN** a user hovers, taps or keyboard-focuses an hour in the preview
- **THEN** a tooltip shows the hour range, the fee in SEK/kWh and the matching rule number or "All other times", and each hour carries the same text as its accessible name and title

#### Scenario: Holiday toggle fully visible
- **WHEN** the editor is shown at any width
- **THEN** the holiday toggle switch is rendered in full (not clipped), laid out like other Settings toggles (switch first, label beside it)

### Requirement: Chart price breakdown uses the per-slot fee
The schedule chart's import price breakdown (spot vs. tax/fees) SHALL subtract the transfer fee resolved for each slot's start time (wall-clock in the configured `timezone`, falling back to `Europe/Stockholm` when unset — the same zone the backend uses) in Time-of-use mode, and the flat fee in Flat mode or when a slot time is unavailable.

#### Scenario: Winter weekday slot breakdown
- **WHEN** Time-of-use mode has a rule "Nov–Mar, Mon–Fri, 06–22 → 0.76" and the user inspects the price at Tue 10:00 in January
- **THEN** the breakdown's spot part equals `price / (1 + vat) − energy_tax − 0.76`

#### Scenario: Non-Stockholm timezone
- **WHEN** `timezone` is `Europe/Helsinki` and a slot starts at 04:30 UTC on a January Tuesday (06:30 Helsinki, 05:30 Stockholm)
- **THEN** the breakdown applies the 06–22 rule fee, matching the backend
