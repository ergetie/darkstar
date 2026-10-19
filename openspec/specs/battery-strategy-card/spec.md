# Battery Strategy Card

## Purpose

Defines the BatteryStrategyCard component, which shows battery state of charge and target, strategy metrics (S-Index, cycles, held-back safety floor with price reserve) and a 7-day price outlook.

## Requirements
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

The card SHALL display the battery cycles count in its header and, below the SoC section, a vertical stack of the battery stack with its "Held back" figure, the price reserve box, and the S-Index row, followed by the 7-day price outlook using the remaining card height. Unavailable values SHALL display "—".

#### Scenario: All metrics show when data is available
- **WHEN** plannerMeta and batteryCycles are populated
- **THEN** cycles appear in the header, and the battery stack, price reserve box and S-Index row display values

#### Scenario: Metrics show dash when data is unavailable
- **WHEN** plannerMeta is null
- **THEN** S-Index displays "—" and the battery stack area shows a loading placeholder

#### Scenario: Cycles shown in the header
- **WHEN** battery cycles data is available
- **THEN** the header shows it (e.g., "1.2 cycles today") and is empty when unavailable

#### Scenario: Metrics derive from planner data
- **WHEN** the metrics are rendered
- **THEN** they are derived from `plannerMeta`, `batteryCycles`, and `batteryCapacity`

#### Scenario: S-Index formatting
- **WHEN** `plannerMeta.s_index.effective_load_margin` (preferred) or `plannerMeta.s_index.risk_factor` is available
- **THEN** the S-Index is formatted as `×{value}` (e.g., "×1.42")

### Requirement: BatteryStrategyCard displays price outlook as a pixel sparkline

When `priceOutlook` is available, the card SHALL display up to 7 days of price outlook as one vertical bar per day below the metrics, filling the card height that remains after the other sections. When it is not yet available, the card SHALL show skeleton bars and label placeholders instead of text.

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

#### Scenario: Bar color indicates price level
- **WHEN** bars are drawn
- **THEN** the color is `bg-good` for cheap, `bg-warn` for normal, `bg-bad` for expensive, and `bg-muted` for unknown

#### Scenario: Bar height scaling
- **WHEN** bars are scaled
- **THEN** height runs between a visible minimum (cheapest day) and the full plot height (dearest day), so the cheapest day is never invisible
- **AND** when all prices are equal the bars are drawn at a mid height

#### Scenario: Reference line, labels and hover
- **WHEN** `reference_avg` is available
- **THEN** a dashed reference line is shown on the same scale
- **AND** day labels and `avg_spot_p50` values are displayed below the bars
- **AND** hovering a bar shows that day's price and, when known, its low and high values

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

### Requirement: BatteryStrategyCard displays a SOC context line
The card SHALL display a single-line context message below the SoC→Target display describing the current strategy intent. The message SHALL be derived from the schedule slot action and price outlook context. When insufficient data is available to derive a message, no context line SHALL be displayed.

#### Scenario: Context line shows charging intent
- **WHEN** the current slot action is `charge` and upcoming days have cheap prices
- **THEN** the context line reads "charging ahead of cheap D1→D3" or similar

#### Scenario: Context line shows discharge intent
- **WHEN** the current slot action involves export or discharge and prices are high
- **THEN** the context line indicates exporting or discharging

#### Scenario: No context line when data insufficient
- **WHEN** price outlook data is unavailable
- **THEN** no context line is displayed

---

### Requirement: BatteryStrategyCard displays reference average in the sparkline
When `priceOutlook.reference_avg` is present and non-null, the price bars SHALL display a dashed horizontal line at the vertical position corresponding to `reference_avg`, on the same height scale as the bars, spanning the full width of the plot. The `reference_avg` value SHALL NOT be shown as a text label.

#### Scenario: Reference line shown when reference_avg is available
- **WHEN** `priceOutlook.reference_avg` is present
- **THEN** a dashed line is positioned within the plot at the height the bar scale gives that value
- **AND** no text label for the reference value is displayed

#### Scenario: No reference line when reference_avg is null
- **WHEN** `priceOutlook.reference_avg` is null
- **THEN** no reference line is displayed

### Requirement: BatteryStrategyCard shows all content without tab interaction
The card SHALL display SoC, metrics, and price outlook all in a single scrollable view. There SHALL be no tab toggle, no hidden sections, and no click required to see any content.

#### Scenario: All content visible on load
- **WHEN** the user views the BatteryStrategyCard
- **THEN** SoC, metrics grid, and price outlook are all visible without any click or tab selection

### Requirement: BatteryStrategyCard displays a stacked battery bar of what is held back

When `plannerMeta.s_index.safety_floor` has `min_soc_kwh` and `calculated_floor_kwh` and `batteryCapacity` > 0, the card SHALL display a horizontal battery bar whose width is the full battery capacity, split in order into zones: Min SoC, Deficit, Weather, Price, Tradable. Below it the card SHALL show "Held back" and a legend of zones.

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

#### Scenario: Zone sizing rules
- **WHEN** zones are computed
- **THEN** Deficit and Weather are the capped values that together equal `calculated_floor_kwh - min_soc_kwh`, where Deficit is the effective reserve (`effective_reserve_kwh`, falling back to `base_reserve_kwh`) limited to that amount and Weather is the remainder
- **AND** Price is only `max(0, final_floor_kwh - calculated_floor_kwh)`, so the zones do not add the full price reserve to the deficit because the planner combines the two floors with a maximum
- **AND** Tradable is `capacity - final floor`, never negative
- **AND** the final floor is `final_floor_kwh`, or `calculated_floor_kwh` when `final_floor_kwh` is absent

#### Scenario: Fill, markers and hover
- **WHEN** the bar is rendered
- **THEN** it is filled zone by zone up to the current SoC, with a marker for the target SoC and a second marker for the final floor
- **AND** zones smaller than 0.01 kWh are not drawn
- **AND** hovering a zone shows its name and kWh

#### Scenario: Held back figure and legend
- **WHEN** the bar is shown
- **THEN** below it the card shows "Held back" with the final floor in kWh and as a percentage of capacity
- **AND** a legend lists every zone with its kWh, with zones holding no energy shown muted

#### Scenario: Loading placeholder
- **WHEN** the data is unavailable
- **THEN** a loading placeholder is shown instead of the bar

### Requirement: BatteryStrategyCard explains the price reserve in plain language

When `plannerMeta.s_index.safety_floor.price_reserve_reason` is present, the card SHALL display a price reserve box with a one-sentence title and, where useful, a detail line, for every reason. When the reason is missing, no box SHALL be shown.

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

#### Scenario: Active reason text
- **WHEN** the reason is `active`
- **THEN** the title is "Holding {applied} kWh extra for {weekday}" when `price_reserve_applied_kwh` is above 0.05, otherwise "{sized} kWh wanted for {weekday}, already covered by the safety buffer"
- **AND** the detail line compares costs ("charging now ~{x} öre vs ~{y} öre on {weekday}") when both are known
- **AND** it adds "limited by battery size" when `price_reserve_capped_by` is `usable_capacity` or "limited by charging time left" when it is `known_window_charge`

#### Scenario: Reasons with no extra reserve
- **WHEN** the reason is `own_day_cheaper`
- **THEN** the title is "No extra reserve: {weekday} looks cheaper to charge", with the cost comparison
- **WHEN** the reason is `below_threshold`
- **THEN** the title is "No extra reserve: price gap too small to pay off", with the cost comparison
- **WHEN** the reason is `no_net_load`
- **THEN** the title is "No extra reserve: solar should cover {weekday}"
- **WHEN** the reason is `no_charge_capacity`
- **THEN** the title is "No extra reserve: no charging time left before {weekday}"

#### Scenario: Disabled or other reason
- **WHEN** the reason is `disabled`
- **THEN** the title is "Price reserve is turned off"
- **WHEN** the reason is any other (such as an unavailable forecast)
- **THEN** the title is "No extra reserve: price forecast unavailable"

#### Scenario: Weekday and highlight
- **WHEN** the weekday is rendered
- **THEN** it comes from `unseen_window_start`, or reads "the next unknown day" when missing
- **AND** the box is highlighted when the Price zone is above 0.01 kWh and muted otherwise
