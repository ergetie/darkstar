## 1. Backend

- [x] 1.1 Extract `_resolve_period` in `backend/api/routers/energy.py` and use it in `/api/energy/range` (behaviour unchanged)
- [x] 1.2 Add `GET /api/energy/cost-series` (hourly for one day, daily otherwise, running net, started slots only, error field on an invalid custom range)
- [x] 1.3 Add `_tag_price_source` in `backend/api/routers/schedule.py` and apply it in `/api/schedule` and `/api/schedule/today_with_history`
- [x] 1.4 Tests: `tests/api/test_energy_cost_series.py`, `tests/api/test_schedule_price_source.py`; add the route to the route snapshot and endpoint smoke tests

## 2. Battery & Strategy card

- [x] 2.1 Extend the planner meta types in `frontend/src/lib/api.ts` with the final floor and price reserve fields
- [x] 2.2 Stacked battery bar with Min SoC, Deficit, Weather, Price and Tradable zones, filled to current SoC, with target and floor markers, "Held back" and a legend with kWh
- [x] 2.3 Price reserve box with a plain-language reason for every `price_reserve_reason`
- [x] 2.4 S-Index on one row, cycles in the header, large SoC to target
- [x] 2.5 7-day price outlook as coloured bars filling the remaining height, dashed reference line, skeleton loading
- [x] 2.6 Update `BatteryStrategyCard.logic.test.ts`

## 3. Dashboard layout and Smart Advisor removal

- [x] 3.1 Delete `SmartAdvisor.tsx`, the advice fetch and state in `Dashboard.tsx`, `computeTodaySummary` and `Dashboard.todaySummary.test.ts`
- [x] 3.2 Place Grid & Financial in column 1 spanning rows 1-2; PowerFlow column 2 row 1; Resources column 2 row 2; Battery column 3 rows 1-2

## 4. Grid & Financial card

- [x] 4.1 Single-column breakdown rows
- [x] 4.2 One-line segmented period control (Today, Yesterday, 7d, 30d, Custom)
- [x] 4.3 `CostSeriesChart.tsx` with pure geometry, running net line, faint bars, hover readout, reduced-motion support; `Api.energyCostSeries` in `lib/api.ts`
- [x] 4.4 Tests: `CostSeriesChart.geometry.test.ts`
- [x] 4.5 Remove the battery capacity label from the Energy Resources header

## 5. Schedule Overview chart

- [x] 5.1 Add `lib/chartTokens.ts` (token colours, grid alpha, dark-theme check) with tests
- [x] 5.2 Add `ChartCard.logic.ts` (slot info, compact line, action marks, estimated ranges, actual/plan split) with tests
- [x] 5.3 Rework `ChartCard.tsx`: price area, SoC line, thin PV/load, action strip, actual solid / plan dashed, legend, NOW line and label, hover guide, full-width plot, PV gradient, dark-mode glow
- [x] 5.4 Fixed info panel (compact line, Details toggle remembered in `localStorage`) replacing the floating tooltip and mobile tap panel; update `ChartCard.selection.test.tsx`
- [x] 5.5 Estimated-price region (hatch, label, badge) from `price_source`
- [x] 5.6 Redraw on theme switch; bump the overlay storage version

## 6. EV card and design system

- [x] 6.1 Single charger fills the cell with actions pinned to the bottom (`EVChargingCard.tsx`, EV tab in `CommandDomains.tsx`); update `CommandDomains.test.tsx`
- [x] 6.2 Replace hard-coded colours with theme tokens; dark text on gold buttons (`.text-on-accent`)
- [x] 6.3 Add `.battery-stack*`, `.price-sparkline*`, `.cost-chart-*`, `.text-on-accent` and schedule-chart styles to `index.css`; show them in `DesignSystem.tsx`

## 7. Verification

- [x] 7.1 Frontend tests, lint and type check pass
- [x] 7.2 Backend API tests pass
