## Why

The current financial comparison depends on a simulated self-use battery, calibrated losses, and a monetary value for remaining battery energy. Replace it with a transparent bill comparison between the whole Darkstar-controlled installation and a grid-only home covering the same recorded consumption at the same per-slot tariff.

## What Changes

- Introduce a per-slot grid-only baseline: `(load_kwh + water_kwh + ev_charging_kwh) * import_price_sek_kwh`, summed over the selected period.
- Compare against measured `import_kwh * import_price_sek_kwh - export_kwh * export_price_sek_kwh` over exactly the same eligible completed slots. Positive difference means the wear-inclusive DS comparison cost is lower.
- Add the existing configured battery-wear calculation to DS cost on both the card's wear-inclusive comparison and solid DS chart line; grid-only wear is zero. Main Savings is grid-only cost minus DS electricity cost minus DS wear, with wear shown as a separate component and added exactly once.
- Show one signed **DS vs grid-only** figure and a dotted **Grid-only** chart line. Explain the baseline briefly in the existing info panel.
- Return covered segments alongside bucket totals so chart lines and shading break at excluded slots, including gaps inside an hourly/daily bucket.
- Position charts by elapsed UTC time with installation-local labels: support 23/25-hour DST days and distinguish repeated hours by position and UTC offset, including the Actual-only fallback.
- Keep actual electricity cost, the separate wear-inclusive figure, and the Grid Import, EV, Export Rev, Battery Charge and Battery Wear breakdown rows. Battery Charge is informational because its cost is already included in Grid Import, so it is never deducted twice. Remove the Self-Use Saved row and tooltip. The DS comparison side includes configured measured battery wear; the grid-only side has zero battery wear. Both exclude stored-energy valuation, fixed fees and capital costs.
- Support solar-only, battery-only and grid-only installations without requiring battery SoC, efficiencies, calibration history, or forecasts.
- **BREAKING**: retire the legacy `baseline`, `baseline_*` point fields, and `battery_comparison` response contract from `/api/energy/cost-series`; replace them with `grid_only_comparison`. Update bundled API types, consumers and fixtures together.
- Stop self-use simulation and calibration work on the financial API request path. Preserve recorded data, measurement provenance and independently used audit tooling.

## Capabilities

### New Capabilities

- `grid-only-comparison`: Defines per-slot grid-only bill accounting, measured DS accounting, input eligibility, coverage, and aggregation without a battery model.

### Modified Capabilities

- `no-darkstar-baseline`: Retire the plain self-use battery baseline and its inventory valuation requirements.
- `battery-comparison-calibration`: Retire financial comparison calibration and configured-loss fallback requirements.
- `energy-totals-api`: Replace financial comparison response fields with explicit grid-only summary and series data, preserving actual metered accounting.
- `grid-financial-wear-display`: Replace the savings line, comparison details and chart with a wear-inclusive DS versus grid-only comparison; preserve actual electricity and separate wear figures.

## Impact

- Backend: `backend/api/routers/energy.py`, a focused grid-only accounting helper, and relevant energy API tests. Remove retired comparison execution/cache code from this router; keep modules used by history-audit tools.
- Frontend: `frontend/src/lib/api.ts`, `CommandDomains.tsx`, `CostSeriesChart.tsx`, their tests, and `/design-system` financial chart fixtures.
- No dependencies, database/schema changes, planner/executor changes, configuration changes, documentation directory edits, or git staging/commits.
