## Why

The house battery has a manual Top Up, but there is no way to say "charge the car now to X%". An EV plug-in outside the plan is switched off by the executor on the next tick, because charger on/off is derived only from the plan. Separately, the power-flow EV node never shows the car's SoC: the dashboard reads a flat `ev_soc` key that the backend never emits, so the node can only say "plugged" or "away", and plug/charging state is not visually distinct.

## What Changes

- **Manual EV charge ("Charge now")**: per-charger manual charge to a target SoC, started from the command bar, visible and stoppable on the EV card. It charges at the charger's `max_current_a` (or an optional user-chosen current on `type: current` chargers; binary chargers are simply switched on), always inside fuse/load-balancer limits. It ends when the car reaches the target SoC, when the car is unplugged, when the user stops it, or at a safety timeout. It does not replace the charger's goal; afterwards control returns to the plan and a replan is triggered.
- **House Top Up ends at target**: today it ignores the target and simply expires after 60 minutes. It SHALL end when battery SoC reaches the target (24 h safety timeout), with the target limited to `min_soc_percent`–100.
- **SoC stepper for both top-ups**: shared stepper where −/+ move in 15% steps and tapping the number allows typing an exact value (house: min SoC–100, EV: 1–100). Replaces the fixed 30/50/80/100 list of the house battery Top Up and is used by the new EV control.
- **Power-flow EV node**: shows SoC directly for the single-charger case, with state icons: lightning = charging (with `SoC → target`), plug = plugged in and idle, unplug = not connected. Multi-charger keeps the aggregate plus the existing popup.
- **Bug fix**: EV node SoC comes from the per-charger `ev_chargers` list instead of the never-emitted `ev_soc` key.

## Capabilities

### New Capabilities
- `ev-manual-charge`: per-charger manual "charge now to target SoC" override, its lifecycle, executor precedence, API and UI.
- `powerflow-ev-node`: what the power-flow EV node displays (SoC, target, connection/charging state icons).

### Modified Capabilities
- `executor`: `force_charge` quick action ends at target SoC instead of after a fixed duration.
- `command-bar`: Top Up target selector becomes a 15%-step stepper with exact-value entry; a new EV Charge control is added.

## Impact

- **Executor**: `executor/engine.py` (`_charger_should_be_on`, the 3 EV decision sites, `_control_ev_charger`/`_control_ev_charger_current`, EV SoC/plug read per tick), load balancer target input.
- **Backend**: `backend/api/routers/ev.py` (new manual-charge endpoints, status in `GET /api/ev/chargers`), `backend/core/ev_state.py` (persisted manual-charge entry), websocket event, route snapshot test.
- **Frontend**: `CommandBar.tsx`, new shared stepper component, `EVChargingCard.tsx`, `PowerFlowCard.tsx`, `PowerFlowRegistry.ts`, `Dashboard.tsx`, `lib/api.ts`, design-system showcase.
- No new dependencies (lucide-react already provides `Zap`, `Plug`, `Unplug`). No DB schema change.
