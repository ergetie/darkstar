## Why

The planner treats every kWh the wallbox delivers as a kWh in the car, but an EV loses a fixed overhead while charging (~0.25 kW) plus energy on every start. Production data (24 Sep – 10 Oct 2026, TeslaMate vs go-e meter) shows ~95% efficiency on normal days but only 58% for 1-phase ~2 kW sessions, which the load balancer creates as overload relief; ~14.5 kWh was lost in 10 days. The planner cannot prefer fewer, high-power sessions because it does not see these losses.

## What Changes

- New per-charger EV loss settings in the EV tab: charging overhead (kW, default 0.25), loss per start (kWh, default 0.15), charge efficiency (%, default 95), and an optional car "energy added" sensor.
- Kepler credits the EV goal with `efficiency × wallbox energy − overhead × charging hours − start loss × starts`, while grid import still pays the full wallbox energy. Starts are modelled so the planner avoids on/off patterns.
- Darkstar records car-side energy per slot (from the energy-added sensor, or SoC change × battery capacity as fallback) next to the existing wallbox energy, via an automatic DB migration.
- The three loss values are learned automatically per charger from that history; learned values replace the configured defaults once enough clean data exists.
- The load balancer pauses the charger instead of switching to 1-phase relief while the EV goal is on track; 1-phase relief stays for goals at risk and for plan slots that charge from solar surplus (pausing would export that power). A charger with no active goal counts as not at risk and is paused.

## Capabilities

### New Capabilities
- `ev-charging-losses`: EV loss settings, Kepler loss modelling (overhead, start loss, efficiency), car-side energy recording and automatic learning of the loss parameters.

### Modified Capabilities
- `phase-load-balancing`: overload handling prefers pause over 1-phase relief when the EV goal is on track, except in solar-surplus slots.
- `ev-target-charging`: goal energy delivered to the car is counted after charging losses.

## Impact

- Planner: `planner/solver/kepler.py`, `planner/solver/types.py`, `planner/solver/adapter.py`, `planner/pipeline.py`.
- Executor: `executor/load_balancer.py`, `executor/engine.py` (reuses `executor/goal_risk.py` unchanged).
- Learning/DB: `backend/learning/models.py`, recorder, new alembic migration.
- Config: `config.default.yaml`, config validation, Settings UI EV tab and settings search.
- No new dependencies.
