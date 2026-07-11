# Delta: planner

## REMOVED Requirements

### Requirement: Simulation SoC projection reflects total battery charge within the SoC band

**Reason**: The `POST /api/simulate` endpoint this requirement governs is deleted in this change. It was broken (`'dict' object has no attribute 'iterrows'`) and dead — its only callers were unrouted archived frontend pages. The user chose deletion over repair.

**Migration**: None required. No live consumer exists. Schedule visualization on the dashboard reads the planner's published schedule directly and is unaffected. If a schedule dry-run capability is ever wanted again, it should be designed fresh against the current planner pipeline.
