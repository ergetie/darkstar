## REMOVED Requirements

### Requirement: Executor fetches current Nordpool import price for battery cost tracking

**Reason**: Battery cost tracking is removed by this change. The `BatteryCostTracker`, the `battery_cost` table, and the `_update_battery_cost` tick step no longer exist, so the per-tick Nordpool price fetch that existed solely to feed them has no remaining purpose. The value it computed had no reader anywhere in the codebase — `get_current_cost()` and `reset()` had zero callers, no API route exposed it, and no frontend consumed it — while the fetch, a fresh database engine, and a row write ran on every 5-second tick.

**Migration**: None required for users. Battery economics used by the planner come from `battery_economics.battery_cycle_cost_kwh` in configuration, which is a separate mechanism and is unchanged; the `battery-cost-integrity` capability continues to govern it. Planning, dashboard figures, and executor decisions are unaffected because nothing read the tracked value. Operators requiring Nordpool prices inside the executor tick for a future purpose should reintroduce the fetch alongside the consumer that needs it.
