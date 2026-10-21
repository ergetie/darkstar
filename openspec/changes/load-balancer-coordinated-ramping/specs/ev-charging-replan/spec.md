## REMOVED Requirements

### Requirement: Sustained balancer throttling triggers an early replan
**Reason**: The balancer-triggered replan passes no fuse information to the planner, fires every 30 minutes while an EV is throttled, counts any EV below its maximum as constrained forever, and shares a rate-limit slot with manual-charge replans. Plans now respect the fuse limits directly (see `planner` and `grid-power-limits`), so a replan cannot help.
**Migration**: `load_balancing.replan_after_throttled_s` is removed from the config (see `config-migration`). Plug-in, unplug, failure/recovery and goal-change replans are unchanged.
