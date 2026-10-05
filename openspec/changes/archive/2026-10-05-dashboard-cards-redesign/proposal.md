## Why

The dashboard cards had drifted from what the planner now does and wasted space:

- The Battery & Strategy card showed only the deficit-based safety floor. It ignored the price reserve (the extra energy held for a cheap-to-store, expensive-to-buy unseen day), and it showed the deficit before the risk cap, so the numbers did not add up to the floor the planner actually used.
- The Smart Advisor card gave users nothing they could act on and took a full grid cell.
- The Grid & Financial card was cramped, with a two-column breakdown and no view of how the cost developed over the period.
- The Schedule Overview chart had no clear hierarchy (price, SoC, forecasts and actions all competed), the floating tooltip caret was misaligned near the left edge, forecast-priced hours looked the same as published ones, and several colours were unreadable in light mode (chart, EV card, gold buttons).

## What Changes

- **Battery & Strategy card**: a stacked battery bar shows what is held back (Min SoC, Deficit capped to its risk limit, Weather, and the part the price reserve adds on top of the deficit floor, then Tradable), filled up to the current SoC, with target and floor markers. "Held back" shows the final floor the planner used. A price reserve box explains in plain language why the reserve is or is not active. S-Index is one row, cycles move to the header, SoC to target is large, and the 7-day price outlook is coloured bars that fill the remaining height.
- **Smart Advisor removed from the dashboard**: component, advice fetch and today-summary helper (and its test) are deleted. The backend advice endpoint and advisor engine are not touched.
- **Dashboard layout**: Grid & Financial moves to column 1 spanning both bento rows; PowerFlow and Resources stay in column 2; Battery & Strategy keeps column 3.
- **Grid & Financial card**: one row per figure, a one-line period control (Today, Yesterday, 7d, 30d, Custom) and a new cost chart (hourly for one day, daily for longer periods) with a running net line.
- **New endpoint** `GET /api/energy/cost-series` feeds that chart, priced like `/api/energy/range`. The period handling is now a shared helper used by both endpoints.
- **Schedule slots carry `price_source`** (`nordpool` or `forecast`) in `/api/schedule` and `/api/schedule/today_with_history`.
- **Schedule Overview chart redesign**: clearer hierarchy, actions as marks on a strip, actual solid / plan dashed, a fixed info panel instead of the floating tooltip and the mobile tap panel, estimated-price hours marked from `price_source`, full-width plot, theme-token colours that repaint on theme switch. Saved overlay choices are reset once.
- **EV dashboard card**: a single charger fills the cell with its actions at the bottom; hints and badges use theme colours so they read in light mode; text on gold buttons is dark.
- **Design system**: new CSS for the battery stack, price bars, cost chart, schedule chart panel and an on-accent text colour.
- Energy Resources card no longer shows the battery capacity label next to its title (the Battery card shows capacity).

## Capabilities

### New Capabilities
- `schedule-price-source`: schedule slots say whether their price is published or forecast.

### Removed Capabilities
- `smart-advisor`: spec deleted with the dashboard card (OpenSpec cannot archive a spec emptied to zero requirements).

### Modified Capabilities
- `battery-strategy-card`: SoC display, strategy metrics, floor breakdown, price reserve explanation, S-Index and price outlook presentation.
- `dashboard-layout`: bento cell layout and the slot info panel replacing the mobile-only selection panel.
- `grid-financial-wear-display`: breakdown layout, period control and cost chart.
- `energy-totals-api`: new cost-series endpoint.
- `chart-planned-actual-display`: actual solid / plan dashed, actions as strip marks, estimated prices, info panel, theme colours.
- `ev-dashboard-card`: single-charger layout and light-mode colours.

## Impact

- **Code (frontend)**: `BatteryStrategyCard.tsx`, `ChartCard.tsx`, new `ChartCard.logic.ts`, new `lib/chartTokens.ts`, new `CostSeriesChart.tsx`, `CommandDomains.tsx`, `EVChargingCard.tsx`, `Dashboard.tsx`, `lib/api.ts`, `index.css`, `DesignSystem.tsx`. Deleted: `SmartAdvisor.tsx`, `Dashboard.todaySummary.test.ts`.
- **Code (backend)**: `backend/api/routers/energy.py` (new endpoint, shared `_resolve_period`), `backend/api/routers/schedule.py` (`_tag_price_source`).
- **Tests**: new tests for the chart logic, chart tokens, cost chart geometry, cost-series endpoint and price source tagging; route snapshot and endpoint smoke tests include the new route; existing card tests updated.
- **API**: one new read-only endpoint; one new field on schedule slots. No breaking change; the advice endpoint stays.
- **Database, config, dependencies**: none.
- **Users**: saved chart overlay choices reset once (storage version bump); everything else is visual.
