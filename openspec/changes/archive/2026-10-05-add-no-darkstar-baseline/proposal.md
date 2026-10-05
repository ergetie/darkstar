## Why

The Grid & Financial card shows what energy cost, but not what it would have cost without Darkstar. The nearest figure, "Self-Use Saved", counts all load not bought from the grid (solar and battery together) and says nothing about what Darkstar's scheduling added. Users cannot see whether the system is paying off.

## What Changes

- Replay each period's recorded slots through a **plain self-use inverter baseline**: the same house, solar and battery, but with the battery charging only from PV surplus, discharging only to cover load, never charging from the grid and never exporting from the battery. The baseline is priced with the same import/export prices as the real figures and carries battery wear at the same cycle cost.
- `GET /api/energy/cost-series` returns, in addition to today's fields, a running baseline cumulative per point and a period `baseline` summary (baseline net, baseline wear, baseline net incl. wear, saving incl. wear). `baseline` is `null` when `system.has_battery` is false.
- The Grid & Financial card shows a "Without Darkstar" line with the saving beneath the existing net-incl-wear line, hidden without a battery.
- The cost chart draws the baseline as a second, dashed line on the same scale as the real net line, with the legend entry "no Darkstar" and the baseline total in the hover readout.
- Existing fields, the headline Net and `/api/energy/range` are unchanged.

## Capabilities

### New Capabilities
- `no-darkstar-baseline`: how the "without Darkstar" baseline is simulated from recorded slots (inputs, battery rules, starting state, pricing, wear, when it is unavailable).

### Modified Capabilities
- `energy-totals-api`: the cost series response gains the per-point baseline running total and the period `baseline` summary.
- `grid-financial-wear-display`: the card gains the "Without Darkstar" comparison line and the chart gains the baseline line.

## Impact

- Backend: new `backend/baseline.py` (pure simulation), `backend/api/routers/energy.py` (cost-series reads battery columns and config and adds the baseline fields), response model if one exists for the endpoint.
- Frontend: `frontend/src/lib/api.ts` (types), `frontend/src/components/CommandDomains.tsx` (card line), `frontend/src/components/CostSeriesChart.tsx` (second line, legend, hover, scaling).
- No database schema change, no new dependencies, no new config keys (uses `battery.*`, `battery_economics.battery_cycle_cost_kwh`, `system.has_battery`).
- Tests: unit tests for the simulation, endpoint tests, chart geometry and card tests.
- Known limitation: EV charging and water heating are replayed at the hours they really happened, though without Darkstar they would have run at other hours. The saving is therefore conservative; the card says so on hover.
