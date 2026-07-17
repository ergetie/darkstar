# Delta: Multi-Day Deferral Controller

## MODIFIED Requirements

### Requirement: MultiDayPlanner is load-type agnostic
The `MultiDayPlanner` SHALL NOT contain any EV-specific logic. Its interface SHALL accept only: `remaining_kwh` (float), `deadline` (datetime), `daily_prices` (list of float), `max_daily_kwh` (list of float), `min_daily_fraction` (float, optional), and `min_chunk_kwh` (float, optional, default 0 = no chunk constraint). It SHALL return a dict mapping date to quota kWh. The caller is responsible for computing `min_chunk_kwh` from device knowledge (e.g. the smallest energy the downstream solver can schedule in one slot); the planner itself SHALL remain device-agnostic.

#### Scenario: Non-EV hypothetical consumer
- **WHEN** a pool heater controller calls `MultiDayPlanner` with `remaining_kwh=100`, a deadline 5 days away, and daily prices
- **THEN** the planner SHALL return valid daily quotas without requiring any EV-specific parameters

#### Scenario: Chunk parameter is optional and backward compatible
- **WHEN** `compute_quota` is called without `min_chunk_kwh`
- **THEN** the allocation behavior SHALL be unchanged from the pre-chunk implementation

## ADDED Requirements

### Requirement: Daily quotas respect the minimum schedulable energy chunk
When `min_chunk_kwh > 0`, every day's returned allocation SHALL be either 0 or at least `min_chunk_kwh`. After the existing price-weighted allocation, floor, cap, and rescale steps, any day allocated a nonzero amount below `min_chunk_kwh` SHALL be zeroed and its energy redistributed to the cheapest day(s) that meet (or can be raised to meet) the chunk within their capacity caps. The redistribution SHALL preserve the total allocation and SHALL never push a day above its capacity cap.

The caller (pipeline) SHALL compute `min_chunk_kwh` per charger as the smallest energy the solver can schedule in one slot: `min_power_kw × slot_h` for `type: current` chargers, `max_power_kw × slot_h` for `type: binary` chargers.

#### Scenario: Sub-chunk slices are consolidated instead of stranding the goal
- **WHEN** `remaining_kwh=2.6` is split across 2 days and `min_chunk_kwh=2.425`
- **THEN** no day SHALL receive a nonzero allocation below 2.425 kWh
- **AND** the full 2.6 kWh SHALL land on a single day (the cheaper of the two with capacity)

#### Scenario: Allocations at or above the chunk are untouched
- **WHEN** every day's price-weighted allocation is already >= `min_chunk_kwh`
- **THEN** the allocation SHALL be identical to the result without the chunk constraint

#### Scenario: Zero chunk disables the constraint
- **WHEN** `min_chunk_kwh=0`
- **THEN** allocations of any size SHALL be permitted (existing behavior)

### Requirement: Goals smaller than one chunk are floored to one chunk
When `0 < remaining_kwh < min_chunk_kwh`, the planner SHALL allocate exactly `min_chunk_kwh` to the cheapest day with sufficient capacity, rather than returning an undeliverable sub-chunk allocation or an empty allocation. This deliberately overshoots the goal by less than one chunk — the downstream device (e.g. an EV's battery management) bounds actual delivery.

#### Scenario: Tiny goal still gets one deliverable slot
- **WHEN** `remaining_kwh=0.3` and `min_chunk_kwh=1.05`
- **THEN** the returned allocation SHALL contain exactly one day with 1.05 kWh
- **AND** all other days SHALL be 0

#### Scenario: Overshoot is bounded by one chunk
- **WHEN** a sub-chunk goal is floored
- **THEN** the total allocation SHALL NOT exceed `min_chunk_kwh` (never more than one slot's minimum energy)
