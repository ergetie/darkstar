## ADDED Requirements

### Requirement: Cost series endpoint returns cost per bucket and the running net
`GET /api/energy/cost-series` SHALL accept the same `period` (`today`, `yesterday`, `week`, `month`, `custom`) and `start_date`/`end_date` parameters as `/api/energy/range`, resolve them with the same shared period helper, and return cost per bucket from the SlotObservation table. For each slot the import cost SHALL be `import_kwh × import_price_sek_kwh` and the export revenue `export_kwh × export_price_sek_kwh`, the same pricing as `/api/energy/range`. Slots SHALL be bucketed by local hour when the range is a single day and by local day otherwise; the response `bucket` SHALL be `"hour"` or `"day"`.

Each point SHALL contain `start` (local ISO time of the bucket), `import_cost_sek`, `export_revenue_sek`, `net_cost_sek` (import minus export) and `cumulative_net_cost_sek` (running sum over the points up to and including it). Points SHALL be ordered by time. Slots that have not started yet SHALL be excluded, even if the recorder holds rows for them. An invalid custom range (bad date format, or end before start) SHALL return an empty `points` list and an `error` message rather than failing.

#### Scenario: Hourly buckets and running net for one day
- **WHEN** a client calls GET /api/energy/cost-series?period=today and two started hours have import cost 8.0 and export revenue 1.0 in the second
- **THEN** `bucket` is "hour", there are two points, and the last point's `cumulative_net_cost_sek` equals the first hour's net plus the second hour's net

#### Scenario: Last cumulative value matches the range total
- **WHEN** a client calls both /api/energy/range and /api/energy/cost-series for the same period
- **THEN** the last point's `cumulative_net_cost_sek` equals the range response's `net_cost_sek`

#### Scenario: Longer period is bucketed by day
- **WHEN** a client calls GET /api/energy/cost-series?period=week
- **THEN** `bucket` is "day" and each point sums one local day

#### Scenario: Future slots are excluded
- **WHEN** the recorder holds rows for slots later today
- **THEN** those slots are not in the response

#### Scenario: Invalid custom range
- **WHEN** `period=custom` with an end date before the start date
- **THEN** the response has an empty `points` list and an `error` message
