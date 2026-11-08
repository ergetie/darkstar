## ADDED Requirements

### Requirement: Fixed fees in actual cost
The system SHALL add fixed fees (grid monthly subscription and supplier yearly fee, both excl VAT) with VAT applied to actual net cost returned by the energy range endpoint.

#### Scenario: Range includes fees
- **WHEN** `/energy/range` is requested for a range
- **THEN** the response contains `fixed_fees_sek` and `net_cost_sek` and `net_cost_incl_wear_sek` include it

#### Scenario: October reconciliation
- **WHEN** fees are 510 kr/month and 384 kr/year, VAT is 25%, range is October 2026 (31 days)
- **THEN** fixed fees equal 678.26 kr

### Requirement: Per-day proration
Fees SHALL be prorated per local calendar day as monthly/days_in_month and yearly/days_in_year, counting days of the requested range regardless of data availability; a DST day counts as one day and today counts as a full day.

#### Scenario: Range without data
- **WHEN** part of the range has no slot data
- **THEN** those days still carry their daily fee

### Requirement: Cost-series stays energy-only
The cost-series endpoint SHALL NOT include fixed fees in any bucket or cumulative value, because the chart compares the actual (DS) line with the grid-only and hindsight lines, which carry no fees.

#### Scenario: Chart lines comparable
- **WHEN** fees are configured non-zero
- **THEN** every cost-series bucket and cumulative value equals the value with zero fees

### Requirement: Fees excluded from comparisons
Fixed fees SHALL NOT affect grid-only comparison, battery benchmark/hindsight or learning metrics.

#### Scenario: Benchmark unchanged
- **WHEN** fees are configured non-zero
- **THEN** grid-only comparison and benchmark results equal those with zero fees

### Requirement: Fixed fees row
The Grid & Financial card SHALL show a "Fixed fees" row between Grid Import and Export Rev.

#### Scenario: Row shown
- **WHEN** the card renders range data
- **THEN** the row displays `fixed_fees_sek`
