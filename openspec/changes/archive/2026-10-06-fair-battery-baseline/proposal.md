## Why

The dashboard compares metered Darkstar costs with an idealised self-use inverter, mixing measurement boundaries, losses and import/export accounting. Its displayed baseline and chart also exclude adjustments included in the savings figure, making the comparison misleading.

## What Changes

- Compare battery management with plain self-use using the same recorded PV, household demand, prices, starting battery charge and a validated installation-specific loss model on both sides.
- Keep EV charging and water heating at their recorded times and amounts. Do not estimate savings from scheduling these loads; plain self-use may discharge into household/water demand, while EV energy is supplied by grid import or PV remaining after non-EV demand.
- Validate calibration on withheld observations and withhold the comparison when available data cannot support it. Do not invent losses, inverter response penalties or replacement load schedules.
- Preserve metered grid costs as actual electricity costs, separately from the estimated battery comparison.
- Make comparison totals, chart endpoints and savings reconcile, including battery wear and the value of the difference in energy left in the battery.
- Label the result as an estimate of battery-management savings and explain its limitations, including 15-minute aggregation.

## Capabilities

### New Capabilities

- `battery-comparison-calibration`: Read-only calibration of inverter and battery losses from recorded observations, with validation and explicit unavailable states.

### Modified Capabilities

- `no-darkstar-baseline`: Apply a shared calibrated model to real battery actions and plain self-use; hold controlled-load schedules fixed and value both results on the same basis.
- `energy-totals-api`: Expose a separate, internally consistent estimated battery comparison without changing metered cost fields.
- `grid-financial-wear-display`: Replace legacy comparison rows/lines with the validated economic estimate while retaining actual cash-flow, wear and EV breakdowns.
- `command-bar`: Display estimated battery savings and comparable chart lines with understandable adjustments and unavailable states.

## Impact

- Backend: `backend/baseline.py`, a dedicated calibration module, observation reads in `backend/api/routers/energy.py`, and focused tests.
- Frontend: cost-series types, Grid domain, cost chart, their tests and Design System sample data.
- Additive cost-series API data; existing metered amounts retain their meaning. Legacy comparison fields remain compatibility data and are not used by the new UI to claim reliable savings.
- No new dependency, database migration, planner/executor change, production configuration write or calibration changes to planner settings.
- Planner archives, automatic replay, settings warnings, power tariffs and EV/water scheduling comparisons remain separate changes.
