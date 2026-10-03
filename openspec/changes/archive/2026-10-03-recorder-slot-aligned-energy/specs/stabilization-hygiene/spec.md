## REMOVED Requirements

### Requirement: Cumulative meter deltas have a plausibility ceiling
**Reason**: The recorder no longer computes cumulative meter deltas; all slot energy is integrated from power history, and `recorder.max_meter_delta_kwh` is removed by startup config migration.
**Migration**: None. Power-history integration is bounded by the existing energy value validation and sanity bounds.
