# Proposal: Load Balancing Completion

## Why

The `universal-load-balancing` and `load-balancing-power-sensors` changes shipped a working per-phase fuse balancer, but the setup around it is confusing and incomplete: priorities are split across two numeric lists in two UI groups, the most consequential decision ("Current (dynamic amps)" in the EV tab) silently changes balancer behavior in another tab, the fixed two-tier give-way order cannot express per-household preferences ("shed the water heater before slowing my EV"), sustained throttling is invisible to the planner until the next scheduled run, and a quiet system (zero-export inverter, change-only execution logging) is indistinguishable from a broken one in the UI. This change completes the load-balancing setup into one clear, configurable experience before the dependent `excess-pv-priority-dispatch` change builds on it.

## What Changes

- **Unified give-way order.** The two-tier structure (all current-type chargers throttle to floor before any shed load is touched) is replaced by a single flat, user-ordered list mixing dynamically-throttled chargers and on/off shed loads. The resolver processes the list top-down: a charger entry gives way by throttling to its floor (then pausing), a shed entry by switching off. Default order preserves today's behavior (chargers first). **BREAKING** for the config schema: `load_balancing.charger_priority` and `loads[].priority` are replaced by one ordered structure (migrated automatically, no user action).
- **Drag-ordered give-way list UI.** One list in the Load Balancing tab, top gives way first. Current-type chargers appear automatically and are read-only except position (their settings live in the EV tab, linked); shed loads are added/removed with editable phases. Each row states in plain words what the balancer can do to it ("Throttle 16→6 A, then pause" / "Switch off"). No numeric priority fields anywhere. The ordered-list widget is built reusable for the upcoming excess-PV sink list.
- **EV tab clarity.** "Current (dynamic amps)" is renamed and gains an explainer at the dropdown stating its consequences: the planner controls amps per slot, the charger is automatically enrolled in load balancing, and it becomes eligible for future PV-surplus charging.
- **Fast-tick validation warning.** Balancer reaction speed and live status both equal `executor.interval_seconds`; enabling load balancing with a slow tick (default 300 s) makes fuse protection nearly useless. Validation and the settings UI warn when `load_balancing.enabled` and the tick is slower than a threshold.
- **Early replan after sustained throttling.** When the balancer has held a charger below its planner target (or paused) for a sustained period (default 10 min), one replan is triggered, at most once per planner interval — so plans stop assuming energy the hardware keeps refusing, without waiting for the next scheduled run's SoC re-read.
- **No-SoC-sensor warning.** A current-type charger without a SoC sensor silently defaults to 0% at plan time, so charging progress and throttling shortfall are untrackable. Config validation and the EV tab warn about it.
- **Balancer intervention notifications.** Shed, pause, and stale-sensor-fallback events (not routine throttle adjustments) are sent through the existing notification path (HA notify with Discord fallback), behind a new settings toggle.
- **Truthful "quiet" UI.** The balancer status card gains a liveness indicator ("updated Xs ago") so near-zero bars (normal for zero-export inverters) read as quiet-and-healthy instead of frozen. The execution history page gains an explainer header (last tick time/status, and that only changes plus one heartbeat per slot are recorded by design).

## Capabilities

### New Capabilities

None — all changes modify existing capabilities.

### Modified Capabilities

- `phase-load-balancing`: the two-tier give-way gate ("EV charger is throttled first", "Prioritized shedding … of on/off loads") is replaced by a single interleaved give-way order; balancer intervention notifications are added; the execution-log throttling requirement is extended to require the history UI to explain the change-only recording.
- `load-balancing-settings`: config schema moves from `charger_priority` + `loads[].priority` to one ordered give-way list (with migration); the settings UI's two labeled groups become one drag-ordered list; new validation warnings (slow executor tick, missing SoC sensor); notifications toggle; live status surface gains a liveness/freshness indicator; EV-tab load-type explainer copy.
- `ev-charging-replan`: a new replan trigger — sustained balancer throttling below the planner target — alongside the existing plug/unplug triggers, rate-limited to once per planner interval.

## Impact

- **Executor** (`executor/load_balancer.py`, `executor/engine.py`, `executor/config.py`): `tick()` give-way resolution rewritten from the two-tier gate (`ev_at_floor_or_paused`) to an ordered interleaved resolver; throttle-duration tracking for the replan trigger; notification dispatch on state transitions.
- **Config & migration** (`config.default.yaml`, `backend/config_migration.py`, `backend/api/routers/config.py`): new ordered give-way structure replacing `load_balancing.charger_priority` and `loads[].priority`; migration from both old fields; new keys for the replan trigger, notification toggle, and tick-speed warning threshold; validation updates.
- **Backend** (`backend/services/scheduler_service.py` or replan path used by plug/unplug triggers, `backend/notify.py` consumers): early-replan wiring; balancer notification routing.
- **Frontend** (`frontend/src/pages/settings/` — LoadBalancingTab, EV tab's EntityArrayEditor, types/logic; `frontend/src/components/LoadBalancerStatusCard.tsx`; execution history page): drag-ordered give-way list (new reusable ordered-list component), EV-tab explainer, warnings, notifications toggle, liveness indicator, history explainer header.
- **Specs**: delta specs for the three modified capabilities.
- **Depends on / enables**: builds directly on `universal-load-balancing` + `load-balancing-power-sensors` (shipped); the reusable ordered-list widget and clarified charger-type UX are prerequisites the deferred `excess-pv-priority-dispatch` change will consume.
