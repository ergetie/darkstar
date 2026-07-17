# Delta: planner

## REMOVED Requirements

### Requirement: Per-device deadline calculation
**Reason**: Superseded by the goal-based EV charging model (`ev-goal-charging-fixes`): per-charger deadlines come from the `ready_by` goal in `data/ev_multi_day_state.json` (see `ev-target-charging` / `per-device-ev-scheduling`), not from the config `departure_time` field. The implementing function `calculate_ev_deadline()` in `planner/pipeline.py` has had no runtime callers since that change and is deleted.
**Migration**: Set the ready-by time on the dashboard EV card (or via the synced HA `input_datetime` entity).
