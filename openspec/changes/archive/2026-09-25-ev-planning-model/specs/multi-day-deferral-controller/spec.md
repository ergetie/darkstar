## REMOVED Requirements

### Requirement: MultiDayPlanner computes daily energy quotas from price forecasts
**Reason**: Pre-solver inverse-price splitting pre-decided per-day energy. Combined with Kepler's per-day caps, it forced charging on expensive days even when every price to the deadline was known (prod 2026-09-25).
**Migration**: Replaced by the tiered deferral value inside Kepler (`ev-deferral-value`).

### Requirement: Minimum daily fraction prevents over-deferral
**Reason**: The 10% floor forced charging on the most expensive days regardless of price.
**Migration**: Over-deferral is now bounded by the risk margin, post-horizon physical capacity, and re-planning (`ev-deferral-value`).

### Requirement: Daily quota respects charger power capacity
**Reason**: Per-day quotas no longer exist.
**Migration**: Post-horizon capacity bounds deferral directly (`ev-deferral-value`: "Post-horizon capacity bounds deferral").

### Requirement: MultiDayPlanner is load-type agnostic
**Reason**: `MultiDayPlanner` is deleted; EV was its only consumer.
**Migration**: None required.

### Requirement: Daily quotas respect the minimum schedulable energy chunk
**Reason**: There are no quotas to consolidate. Kepler models semi-continuous current chargers and fixed-power binary chargers natively.
**Migration**: None required.

### Requirement: Goals smaller than one chunk are floored to one chunk
**Reason**: There are no quotas. Kepler's soft requirement handles sub-chunk goals by scheduling one minimum-power slot.
**Migration**: None required.

### Requirement: MultiDayPlanner handles missing or partial price forecasts gracefully
**Reason**: `MultiDayPlanner` is deleted.
**Migration**: Missing-forecast handling now lives in `ev-deferral-value` ("Deferral pricing degrades conservatively when forecasts are missing").
