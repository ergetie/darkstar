## Why

The main ChartCard renders power bars (load, charge, discharge, export, water heating, EV, etc.) on the `y1`/`y2` axes scaled to `max(gridMaxKw, inverterMaxKw)`, but the PV forecast line on a separate `y4` axis scaled to `solarKwp`. Because the two scales have different maximums, the same power value (e.g. 4 kW) is drawn at a different height for the PV line than for a bar. A recent change unified all bar amplitudes; the PV line was missed, so it can appear taller (or shorter) than a bar at the identical kW, which misleads users reading the chart.

## What Changes

- Compute a single shared power ceiling for the main chart: `max(gridMaxKw, inverterMaxKw, solarKwp)`.
- Apply that shared ceiling to the PV forecast line axis (`y4`) in addition to the bar axes (`y1`, `y2`), so every power element — bars and the PV line — uses one ruler.
- Update both the chart initialization path and the dynamic scale-update path so they stay consistent.
- Net effect: equal kW renders at equal height across all power series, and PV peaks above the grid/inverter limit no longer clip (the ceiling now includes `solarKwp`).

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `chart-planned-actual-display`: add a requirement that all main-chart power series (bars and the PV forecast line) share a single power axis scale, so equal power renders at equal height.

## Impact

- `frontend/src/components/ChartCard.tsx`: static default scales (`y1`/`y2`/`y4`), the chart-init scales block (~line 1227–1239), and the dynamic scale-update effect (~line 1294–1313).
- No backend, API, or data-shape changes. Purely a frontend visual-scaling fix.
