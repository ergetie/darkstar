## Why

On mobile viewports the dashboard schedule chart (`ChartCard`) used Chart.js's floating overlay tooltip, which covered most of the chart, had no positional anchor to a time-slot, and could not be dismissed. Tapping data was not usable on narrow screens.

## What Changes

- The Chart.js floating tooltip is disabled on mobile (viewports < 768 px / below Tailwind `md`).
- Tapping a chart slot selects it and draws a full-height vertical selection band with an amber accent line at that slot position.
- When a slot is selected, `ChartCard` expands downward to reveal an inset panel below the chart timeline showing that slot's values (time heading + each visible series' formatted value, including spot + tax/fees price breakdown).
- Tapping outside the card clears the selection (panel collapses, band disappears, card returns to normal height).
- The selection is cleared automatically on chart data refresh and when the viewport crosses from mobile to desktop.
- Desktop hover-tooltip behavior is unchanged.

## Capabilities

### New Capabilities

_(none)_

### Modified Capabilities

- `dashboard-layout`: Add requirement for mobile chart slot selection panel (replaces floating tooltip on mobile).

## Impact

- `frontend/src/components/ChartCard.tsx` — implementation lives here (already done).
- No API, backend, or routing changes.
