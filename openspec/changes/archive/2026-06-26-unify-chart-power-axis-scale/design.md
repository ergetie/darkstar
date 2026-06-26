## Context

`ChartCard.tsx` draws the main dashboard chart with Chart.js. Power series are split across axes:

- `y1` (left, visible) and `y2` (left, hidden) — all power **bars** (load, charge, discharge, export, water heating + boost, EV, excess-PV sink). Max = `Math.max(scaling.gridMaxKw, scaling.inverterMaxKw)`.
- `y4` (left) — the PV forecast **line**. Max = `scaling.solarKwp`.

Because `y4` uses a different maximum than `y1`/`y2`, equal power renders at unequal height. A prior change unified the bar axes; the PV line axis was not included.

Scales are set in two places that must stay in sync:
1. Chart initialization (`useEffect` building the Chart.js config, ~line 1227–1239).
2. Dynamic scale-update effect that runs when scaling config changes without re-creating the chart (~line 1294–1313).

The static defaults in `defaultChartOptions` (`y1`/`y2` max 9, `y4` max 1.5) are placeholders overridden at runtime by the two paths above.

## Goals / Non-Goals

**Goals:**
- One shared power ceiling for every main-chart power series (bars + PV line), so equal kW = equal height.
- PV peaks that exceed the grid/inverter limit no longer clip off the top.
- Keep the init path and the dynamic-update path consistent.

**Non-Goals:**
- No change to the price axis (`y`), SOC axis (`y3`), or any non-power series.
- No change to backend, API, or data shapes.
- No change to dotted "actual" overlay lines' axis assignment beyond inheriting the shared power scale where they already share a power axis.

## Decisions

**Decision: Shared ceiling = `max(gridMaxKw, inverterMaxKw, solarKwp)`.**
Including `solarKwp` in the max guarantees the PV curve always fits when solar capacity exceeds the grid/inverter rating, while bars still reach the top whenever grid/inverter is the largest. Apply this single value to `y1`, `y2`, and `y4` in both the init block and the dynamic-update effect.

- *Alternative — drop `y4` and put the PV line on `y1`:* cleaner conceptually, but `y4` may carry independent styling/positioning and removing an axis is a larger blast radius. Reusing `y4` with the shared max is the minimal, safe change. Chosen.
- *Alternative — clamp the PV scale to the bar max (exclude `solarKwp`):* would make heights match but reintroduce clipping of sunny-midday PV peaks. Rejected — clipping hides real data.

**Decision: Compute the shared max once and reuse.**
The dynamic-update effect already computes `gridInverterMax`; extend it (and the init block) to fold in `solarKwp`. Keeps the two paths reading from the same expression.

## Risks / Trade-offs

- [On low-power days the whole chart looks short, because the ceiling tracks capacity, not the day's peak] → This is the existing, intended behavior for bars; extending it to the PV line is consistent and was confirmed acceptable with the user.
- [The two scale-setting paths drift out of sync] → Mitigated by using the identical `max(gridMaxKw, inverterMaxKw, solarKwp)` expression in both, and a task to verify both paths.
- [Static defaults (max 9 / 1.5) left inconsistent] → Low risk since runtime overrides them, but update them to a sensible shared placeholder to avoid a flash of mismatched scaling before data loads.
