## MODIFIED Requirements

### Requirement: BatteryStrategyCard displays current SoC and target with color coding
The `BatteryStrategyCard` component (`frontend/src/components/BatteryStrategyCard.tsx`) SHALL display the current battery SoC (from `soc` prop) and the current slot target SoC (from `socTarget` prop) prominently, as large figures separated by an arrow. SoC SHALL be color-coded: green (`text-good`) when > 50%, amber (`text-warn`) when > 20%, red (`text-bad`) when ≤ 20%. Below the figures, the actual kWh SHALL be shown (e.g., "7.2 / 10.0 kWh"), with "—" for values that are unavailable.

#### Scenario: SoC shown in green when above 50%
- **WHEN** `soc` is 75
- **THEN** the SoC value is displayed in the `text-good` color

#### Scenario: SoC shown in amber when between 20% and 50%
- **WHEN** `soc` is 35
- **THEN** the SoC value is displayed in the `text-warn` color

#### Scenario: SoC shown in red when at or below 20%
- **WHEN** `soc` is 15
- **THEN** the SoC value is displayed in the `text-bad` color

#### Scenario: kWh display shown when battery capacity is known
- **WHEN** `batteryCapacity` is 10.0 and `soc` is 72
- **THEN** the card shows "7.2 / 10.0 kWh" below the SoC

### Requirement: BatteryStrategyCard displays strategy metrics in a vertical stack
The card SHALL display the battery cycles count in the card header (e.g., "1.2 cycles today", empty when unavailable). Below the SoC section it SHALL display, in a vertical stack, the battery stack with its "Held back" figure, the price reserve box, and the S-Index on a single row. These SHALL be derived from `plannerMeta`, `batteryCycles`, and `batteryCapacity`. When a value is unavailable, it SHALL display "—". The 7-day price outlook SHALL follow and use the remaining card height.

S-Index is derived from `plannerMeta.s_index.effective_load_margin` (preferred) or `plannerMeta.s_index.risk_factor`, formatted as `×{value}` (e.g., "×1.42").

#### Scenario: All metrics show when data is available
- **WHEN** plannerMeta and batteryCycles are populated
- **THEN** cycles appear in the header, and the battery stack, price reserve box and S-Index row display values

#### Scenario: Metrics show dash when data is unavailable
- **WHEN** plannerMeta is null
- **THEN** S-Index displays "—" and the battery stack area shows a loading placeholder

### Requirement: BatteryStrategyCard displays price outlook as a pixel sparkline
When `priceOutlook` is available, the card SHALL display up to 7 days of price outlook as vertical bars below the metrics. The bars SHALL fill the card height that remains after the other sections, with one bar per day. Bar color SHALL indicate price level: `bg-good` for cheap, `bg-warn` for normal, `bg-bad` for expensive, `bg-muted` for unknown. Bar height SHALL be scaled between a visible minimum (cheapest day) and the full plot height (dearest day), so the cheapest day is never invisible; when all prices are equal, the bars SHALL be drawn at a mid height. A `reference_avg` dashed line SHALL be shown when available, on the same scale. Day labels and `avg_spot_p50` values SHALL be displayed below the bars. Hovering a bar SHALL show that day's price and, when known, its low and high values.

When `priceOutlook` is not yet available, the card SHALL show skeleton bars and label placeholders instead of text.

#### Scenario: Bars render one per day
- **WHEN** `priceOutlook.days` contains 7 entries
- **THEN** 7 colored bars are rendered, each with a height reflecting its price relative to the 7-day range, with day label and price value below

#### Scenario: Dearest and cheapest day heights
- **WHEN** a day has the highest `avg_spot_p50` in the 7-day range
- **THEN** its bar is the full plot height; the cheapest day has the shortest bar, which is still visible

#### Scenario: Equal prices
- **WHEN** all days have the same `avg_spot_p50`
- **THEN** all bars are drawn at the same mid height

#### Scenario: Skeleton while loading
- **WHEN** `priceOutlook` is undefined or has zero days
- **THEN** the card shows skeleton bars and no "loading" text, and marks the area as busy for assistive technology

### Requirement: BatteryStrategyCard displays S-Index with inline decomposition
The card SHALL display the S-Index value on a single row together with a compact decomposition when available. When `plannerMeta.s_index` contains `avg_deficit`, the row SHALL also show, right aligned: `base {base_factor} · deficit +{contribution} · cold +{contribution}`, using 1.00 and 0.00 for missing parts. When `avg_deficit` is unavailable, only the `×{effective_load_margin}` value SHALL be shown.

#### Scenario: S-Index shown with decomposition on one row
- **WHEN** `plannerMeta.s_index.effective_load_margin` is 1.18 and `plannerMeta.s_index` contains `avg_deficit: 0.05`, `temp_adjustment: 0.03`, and `base_factor: 1.10`
- **THEN** the card displays "×1.18" and "base 1.10 · deficit +0.05 · cold +0.03" on the same row

#### Scenario: S-Index shown without decomposition when data missing
- **WHEN** `plannerMeta.s_index.effective_load_margin` is 1.18 but `avg_deficit` is not present
- **THEN** the card displays "×1.18" without a decomposition

#### Scenario: S-Index shows dash when unavailable
- **WHEN** `plannerMeta` is null or `plannerMeta.s_index` has no `effective_load_margin` or `risk_factor`
- **THEN** the card displays "—" for S-Index

### Requirement: BatteryStrategyCard displays reference average in the sparkline
When `priceOutlook.reference_avg` is present and non-null, the price bars SHALL display a dashed horizontal line at the vertical position corresponding to `reference_avg`, on the same height scale as the bars, spanning the full width of the plot. The `reference_avg` value SHALL NOT be shown as a text label.

#### Scenario: Reference line shown when reference_avg is available
- **WHEN** `priceOutlook.reference_avg` is present
- **THEN** a dashed line is positioned within the plot at the height the bar scale gives that value
- **AND** no text label for the reference value is displayed

#### Scenario: No reference line when reference_avg is null
- **WHEN** `priceOutlook.reference_avg` is null
- **THEN** no reference line is displayed

## REMOVED Requirements

### Requirement: BatteryStrategyCard displays Safety Floor with inline breakdown
**Reason**: The deficit-only floor ignored the price reserve and showed the deficit before the risk cap. It is replaced by the battery stack and the "Held back" figure.
**Migration**: See "BatteryStrategyCard displays a stacked battery bar of what is held back".

## ADDED Requirements

### Requirement: BatteryStrategyCard displays a stacked battery bar of what is held back
When `plannerMeta.s_index.safety_floor` has `min_soc_kwh` and `calculated_floor_kwh` and `batteryCapacity` > 0, the card SHALL display a horizontal battery bar whose width is the full battery capacity, split in this order into zones: Min SoC (`min_soc_kwh`), Deficit, Weather, Price, Tradable.

- Deficit and Weather SHALL be the capped values: together they equal `calculated_floor_kwh - min_soc_kwh`. Deficit is the effective reserve (`effective_reserve_kwh`, falling back to `base_reserve_kwh`) limited to that amount; Weather is the remainder.
- Price SHALL be only the part the price reserve adds on top of the deficit floor: `max(0, final_floor_kwh - calculated_floor_kwh)`. The planner combines the two floors with a maximum, so the zones SHALL NOT add the full price reserve to the deficit.
- Tradable SHALL be `capacity - final floor`, never negative.
- The final floor SHALL be `final_floor_kwh`, or `calculated_floor_kwh` when `final_floor_kwh` is absent.

The bar SHALL be filled, zone by zone, up to the current SoC. A marker SHALL show the target SoC and a second marker the final floor. Zones smaller than 0.01 kWh SHALL not be drawn. Hovering a zone SHALL show its name and kWh.

Below the bar the card SHALL show "Held back" with the final floor in kWh and as a percentage of capacity, and a legend with every zone and its kWh (zones with no energy shown muted). When the data is unavailable, a loading placeholder SHALL be shown instead of the bar.

#### Scenario: Floor without price reserve
- **WHEN** capacity is 10 kWh, `min_soc_kwh` 1.0, `calculated_floor_kwh` 3.0, `effective_reserve_kwh` 1.5 and `final_floor_kwh` 3.0
- **THEN** the zones are Min SoC 1.0, Deficit 1.5, Weather 0.5, Price 0.0, Tradable 7.0 kWh and "Held back" shows 3.0 kWh · 30%

#### Scenario: Deficit shown after the risk cap
- **WHEN** `effective_reserve_kwh` is larger than `calculated_floor_kwh - min_soc_kwh`
- **THEN** the Deficit zone equals `calculated_floor_kwh - min_soc_kwh`, Weather is 0, and the zones still add up to the floor

#### Scenario: Price reserve lifts the floor
- **WHEN** `calculated_floor_kwh` is 3.0 and `final_floor_kwh` is 5.5
- **THEN** the Price zone is 2.5 kWh, sitting after Weather, and "Held back" shows 5.5 kWh

#### Scenario: Price reserve already covered by the deficit floor
- **WHEN** `final_floor_kwh` equals `calculated_floor_kwh`
- **THEN** the Price zone is 0 and not drawn, and its legend entry is muted

#### Scenario: Bar filled to current SoC with markers
- **WHEN** the battery holds 4.0 kWh and the target SoC is 60%
- **THEN** the bar is filled up to 4.0 kWh across the zones, the target marker sits at 60% and the floor marker at the final floor

#### Scenario: Unavailable data
- **WHEN** `safety_floor` is missing or capacity is unknown
- **THEN** a placeholder is shown instead of the bar

### Requirement: BatteryStrategyCard explains the price reserve in plain language
When `plannerMeta.s_index.safety_floor.price_reserve_reason` is present, the card SHALL display a price reserve box with a one-sentence title and, where useful, a detail line, for every reason:

- `active`: title "Holding {applied} kWh extra for {weekday}" when `price_reserve_applied_kwh` is above 0.05; otherwise "{sized} kWh wanted for {weekday}, already covered by the safety buffer". The detail line SHALL compare the cost of charging now with the cost on that day ("charging now ~{x} öre vs ~{y} öre on {weekday}") when both costs are known, and SHALL add "limited by battery size" when `price_reserve_capped_by` is `usable_capacity` or "limited by charging time left" when it is `known_window_charge`.
- `own_day_cheaper`: "No extra reserve: {weekday} looks cheaper to charge", with the cost comparison.
- `below_threshold`: "No extra reserve: price gap too small to pay off", with the cost comparison.
- `no_net_load`: "No extra reserve: solar should cover {weekday}".
- `no_charge_capacity`: "No extra reserve: no charging time left before {weekday}".
- `disabled`: "Price reserve is turned off".
- any other reason (such as an unavailable forecast): "No extra reserve: price forecast unavailable".

The weekday SHALL come from `unseen_window_start`, or read "the next unknown day" when it is missing. The box SHALL be highlighted when the Price zone is above 0.01 kWh and muted otherwise. When `price_reserve_reason` is missing, no box SHALL be shown.

#### Scenario: Active reserve
- **WHEN** the reason is `active`, 2.5 kWh is applied, the unseen day is a Thursday, charging now costs 0.42 SEK/kWh and Thursday 0.95
- **THEN** the box reads "Holding 2.5 kWh extra for Thursday" with "Cheaper to store it: charging now ~42 öre vs ~95 öre on Thursday"

#### Scenario: Active but covered
- **WHEN** the reason is `active` and `price_reserve_applied_kwh` is 0 with `price_reserve_kwh` 1.8
- **THEN** the title reads "1.8 kWh wanted for {weekday}, already covered by the safety buffer"

#### Scenario: Capped reserve
- **WHEN** the reason is `active` and `price_reserve_capped_by` is `known_window_charge`
- **THEN** the detail line says the reserve is limited by charging time left

#### Scenario: Not worth it
- **WHEN** the reason is `own_day_cheaper`
- **THEN** the box says no extra reserve is held because the day looks cheaper to charge

#### Scenario: Unknown reason
- **WHEN** the reason is a value not listed above
- **THEN** the box says no extra reserve because the price forecast is unavailable

#### Scenario: No reason available
- **WHEN** `price_reserve_reason` is absent
- **THEN** no price reserve box is shown
