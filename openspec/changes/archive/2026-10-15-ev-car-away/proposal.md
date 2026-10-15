## Why

A Discord user (torleif, 2026-10-13) reported two EV problems while the car is away with a daily goal:

1. The plan for the away car ("assumed plugged") still blocks house battery discharge in the planned EV slots, so the battery sits idle and the house buys grid power at peak price. A solver run reproduced it: identical plans for plugged and assumed-plugged, discharge 0 in the EV slots. This contradicts `ev-goal-lifecycle-feedback`, which promised "no discharge block" for assumed-plugged slots.
2. On desktop the EV card's Clear Goal / Configure Goal buttons are cut off and unreachable (confirmed from the user's screenshot): the card shrinks to the cell height and clips its own content.

Goals are kept when the car is unplugged (decided 2026-10-15): a daily goal must survive the car leaving, and one-off goals already expire after their deadline.

## What Changes

- Assumed-plugged chargers no longer drive the solver's discharge block. Only live-plugged chargers do. Everything else about assumed-plugged planning stays (energy balance, grid-only EV energy, deferral tiers, preview, plug-in reminder).
- When the car is plugged in, the existing plug-in replan produces a plan with the discharge block, unchanged.
- The EV card's awaiting-plug-in text also states that the planned charging does not affect the house battery while the car is away.
- The EV card's action buttons are always visible; when the content does not fit, the content between header and buttons scrolls inside the card.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `per-device-ev-scheduling`: per-device discharge blocking applies only to plugged-in chargers.
- `planner`: "Solver blocks battery discharge during EV charging" is scoped to plugged-in chargers.
- `ev-dashboard-card`: awaiting-plug-in wording mentions the battery is unaffected; action buttons always visible with a scrolling body.

## Impact

- Planner: `planner/solver/kepler.py` (`any_ev_charging` linking and discharge block).
- Frontend: `frontend/src/components/EVChargingCard.tsx` (layout, awaiting-plug-in text), possibly `frontend/src/components/CommandDomains.tsx`.
- Tests: `tests/planner/`, `frontend/src/components/EVChargingCard.test.tsx`.
- No config, API or executor changes.
