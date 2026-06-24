## Context

`ChartCard` renders the schedule chart using Chart.js. On desktop, the library's built-in floating tooltip is used on hover. On mobile the tooltip covered most of the chart area, had no slot anchor, and could not be dismissed — making the chart effectively non-interactive.

The fix is entirely contained within `frontend/src/components/ChartCard.tsx`. No backend changes are required.

## Goals / Non-Goals

**Goals:**
- Replace the mobile tooltip with a tap-driven slot selection model.
- Show selected slot values in an inset panel below the chart on mobile.
- Leave desktop behavior completely unchanged.

**Non-Goals:**
- Redesigning the chart or changing its data/series.
- Changing how values are formatted (reuse existing tooltip formatting logic).
- Any backend, API, or routing changes.

## Decisions

**Disable Chart.js tooltip on mobile, not desktop.**
Chart.js tooltip is configured conditionally: disabled when viewport < 768 px, enabled otherwise. This avoids forking the chart config and keeps the desktop path unchanged.

**Draw selection band via Chart.js plugin API (afterDraw hook).**
A custom plugin draws the vertical amber band at the selected slot index after each render. This keeps the band visually integrated with the chart canvas rather than requiring an absolutely-positioned DOM overlay.

**Expand the card via conditional CSS class, not JS height animation.**
When a slot is selected, the card gets a class that removes a max-height constraint, revealing the inset panel below the chart timeline. CSS transition handles the animation — no JS measurement needed.

**Clear selection on outside tap via document-level click listener.**
A `click` listener on `document` clears selection when the event target is outside the card element. Listener is added/removed with the card's lifecycle to avoid leaks.

## Risks / Trade-offs

- [Chart.js plugin API is internal] → Mitigated: the `afterDraw` hook is a stable, documented extension point in Chart.js v3/v4.
- [Outside-tap detection depends on DOM containment] → Mitigated: standard `contains()` check; robust across all tap targets on the card.
