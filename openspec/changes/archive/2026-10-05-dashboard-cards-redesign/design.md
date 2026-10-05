## Context

- The planner now exposes the final held-back energy and the price reserve decision in `plannerMeta.s_index.safety_floor` (`final_floor_kwh`, `price_reserve_*`, `known_cost_sek_kwh`, `own_day_cost_sek_kwh`, `unseen_window_start`). The card did not use them.
- The planner combines the deficit floor and the price reserve with `max`, not a sum. The card must show it that way or the bar will not match the floor.
- The chart mixed bars, dotted overlays and a floating Chart.js tooltip. Hover and mobile tap used two different mechanisms.
- Colours were hard-coded in several places, so light mode and theme switches were inconsistent.

## Goals / Non-Goals

**Goals:**
- Show what the planner actually holds back, and why, in words a non-technical user can read.
- Use the dashboard space well and drop a card that gave no value.
- Make the schedule chart readable at a glance, with one details mechanism for hover and tap.
- Mark hours priced from a forecast.
- Use design-system tokens so light and dark both read well.

**Non-Goals:**
- No change to the planner, the price reserve rules or any planner output.
- No removal of the backend advice endpoint or advisor engine.
- No database, config or dependency changes; no change to `docs/`.

## Decisions

1. **Battery bar layers.** Zones in order: Min SoC, Deficit, Weather, Price, Tradable. Deficit and Weather are split from the deficit floor's buffer using the capped (effective) reserve, so they sum to the deficit floor. The Price layer is `final_floor_kwh - calculated_floor_kwh`, floored at zero, which is exactly what the reserve adds over the deficit floor (max, not sum). "Held back" is `final_floor_kwh`, falling back to the deficit floor when absent. Zones under 0.01 kWh are not drawn but stay in the legend.
2. **Reserve explanation from `price_reserve_reason`.** One plain sentence per reason (active, own_day_cheaper, below_threshold, no_net_load, no_charge_capacity, disabled, and a fallback for everything else, such as forecast unavailable). The active case distinguishes "extra energy held" from "already covered by the safety buffer" and mentions a physical cap when `price_reserve_capped_by` is set. Prices are shown in öre; the day is named from `unseen_window_start`.
3. **Price outlook as bars.** Bar height is scaled between a visible minimum and 100%, so the cheapest day stays visible; equal prices show mid-height bars. The reference average uses the same scale. A skeleton replaces the old "loading" text.
4. **Advisor removal is frontend-only.** The advice endpoint, price advisor engine and config stay; only the dashboard consumer goes. This avoids a backend break and keeps the endpoint available for other uses.
5. **Cost series endpoint reuses `/api/energy/range` pricing** (slot import/export kWh times the recorded slot prices). Period resolution moves into `_resolve_period`, shared by both endpoints. One day gives hourly buckets, longer periods daily buckets. Slots that have not started are excluded because the recorder can hold future rows, which would flatten the running line to midnight. Invalid custom ranges return an empty series with an `error` field (same non-throwing style as `/api/energy/range`).
6. **Cost chart geometry is a pure function.** One day uses a fixed 00-24 axis so the line grows left to right; longer periods use one slot per day. Bars use the bottom 35% on their own scale; the net line uses the full height with zero always inside. Line colour follows the final net (green when earning, red when paying). Entrance animations are disabled under reduced motion.
7. **`price_source` per slot.** A slot is `nordpool` only when the price feed has a published (not forecast-fallback) price for its local start time; everything else, including slots beyond the published horizon, is `forecast`. The tag is applied in both schedule endpoints after the price overlay and is skipped silently if the overlay fails.
8. **One info panel for hover and tap.** The panel is always visible above the plot. It shows the slot under the cursor (desktop), the tapped slot (mobile) or the current slot. Compact one-line summary by default; a Details toggle (remembered in `localStorage`) shows grouped values. This replaces the floating tooltip (whose caret misaligned near the left edge) and the mobile expanding panel. Mobile tap-to-select, click-away and survival across live updates keep working.
9. **Chart visual hierarchy.** Price is a soft filled area, SoC the strongest line, PV and load thin. Actions (charge, discharge, export, water, EV, excess PV) are marks on a strip under the plot instead of bars. Actual is solid, plan is dashed, with a legend. A NOW line with a label separates past from future. Estimated-price hours get a hatched price area, a faint band, an "ESTIMATED PRICES" label and an "Estimated" badge.
10. **Tokens, not literals.** Chart colours resolve from design tokens at draw time (`lib/chartTokens.ts`), so a theme switch only needs a redraw (a `class` observer on `<html>`). Glow is dark mode only. The EV card and bento period buttons use token classes; a new `.text-on-accent` gives dark text on gold buttons.
11. **Overlay storage version bump** (5 to 6): the Overlays menu changed meaning (actions are now strip marks), so old saved choices are reset once. Alternative (migrate each key) rejected as not worth it.
12. **Single EV charger fills the cell.** With one charger the card stretches and pins its action buttons to the bottom; several chargers scroll inside the cell on desktop without driving the row height.

## Risks / Trade-offs

- [Saved overlay choices reset once] -> one-time, expected; defaults are sensible.
- [Cost chart makes one more request per period change] -> small query, runs in parallel with the range request; failure only hides the chart.
- [Removing the Advisor card removes the only dashboard display of price alerts] -> accepted; the data endpoint remains if a better place is found later.
- [Reserve text depends on planner debug fields] -> every field is optional in the UI; missing data degrades to the fallback sentence or an empty detail line.
