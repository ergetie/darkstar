# Design: Excess PV Priority Dispatch

## Context

Today's excess-PV pipeline: `planner/pipeline.py` pre-computes per-slot excess-PV flags (`excess[t] = pv − load − min_water − min_ev > 0`), `planner/solver/kepler.py` creates binary sink variables (`water_boost[heater][t]`, `custom_entity_active[t]`) gated on those flags AND projected battery SoC ≥ `soc_threshold_percent` (big-M binary `soc_above_threshold[t]`), rewarded with `boost_reward_sek_per_kwh` against export economics. Exactly one sink type is active (`excess_pv_sink` string in `planner/solver/types.py:KeplerConfig`, mapped in `adapter.py`, config in `executor.excess_pv`, parsed by `executor/config.py:ExcessPVConfig`). The executor toggles the custom entity / water boost per schedule. EV charging in the solver is a per-charger binary (`ev_charge[d][t]`) at nominal power — there is no EV surplus concept.

The `universal-load-balancing` change (Change 1, must land first) delivers: `ev_chargers[]` devices with `type: current`, `current_entity`, `min_current_a` (6), `max_current_a`, `phases`; an executor ampere actuation path with kW→A conversion (`amps = floor(kw × 1000 / (230 × active_phases))`); decrease-fast/increase-slow ramping with resume delay + margin; phase-aware accounting from the charger's measured per-phase draw; and a per-phase fuse balancer that caps the final EV amp setpoint every tick.

Physics constraint driving phase switching: a 3-phase charger's minimum is 6 A × 3 × 230 V ≈ 4.14 kW; in 1-phase mode the minimum is ≈ 1.38 kW. The go-e Gemini Flex supports commanded phase-mode switching via an HA entity (MQTT integration). Grid sensors and executor tick run at 5 s.

## Goals / Non-Goals

**Goals:**
- User-configurable, ordered priority list of excess-PV sinks; battery implicitly first (SoC gate unchanged).
- EV as a surplus sink: planner schedules eligibility + expected energy; executor tracks *measured* surplus in real time and modulates charge current within the slot.
- 1↔3-phase switching so small surpluses (1.4–4.1 kW) still charge the car, with contactor-safe hysteresis and dwell time.
- Preserve all existing excess-PV behavior for water heater boost and custom entity (slot-based), including economics and SoC gating.
- Clean config migration from single `sink` to `priority[]`.

**Non-Goals:**
- Real-time re-allocation between non-EV sinks (boost/custom stay schedule-driven; only the EV tracks live surplus in v1).
- Fuse protection (Change 1 owns it; its cap is authoritative over anything this change requests).
- Battery-assist (Change 3) and planner awareness of balancer caps (future work, per Change 1).
- Driving the charger's own built-in PV-surplus logic (Darkstar computes everything; charger stays "dumb").
- V2H / discharging the EV; charging the EV from the house battery (existing EV source isolation preserved).

## Decisions

### D1. Priority ordering is enforced in the MILP via rank-scaled rewards, not cascade constraints
Each sink in `excess_pv.priority[]` gets an effective reward `base_reward × (1 − rank × 0.15)` (rank 0 = first = highest). Since all sinks draw from the same energy balance, the solver feeds higher-reward (higher-priority) sinks first when surplus is scarce and activates several when it is plentiful — exactly the desired semantics. A per-sink `reward_sek_per_kwh` override remains possible for power users. *Alternative rejected:* hard cascade constraints ("sink i+1 only if sink i saturated") — significantly more binaries/big-M rows in an 827-line solver that already has benchmark scripts watching its runtime, for behavior the reward gradient already produces; and it breaks down when a higher-priority sink is unavailable (EV unplugged) mid-horizon.

### D2. EV surplus is a continuous solver variable, output as a per-slot eligibility + energy plan
For each plugged-in `current`-type charger, `ev_surplus_kw[d][t]` is a continuous variable in `[0, charger_max_kw]`, active only where the excess-PV flag is true AND `soc_above_threshold[t]` — mirroring existing sink gating. It enters the energy-balance demand side and earns its rank-scaled reward. It is separate from the existing binary `ev_charge[d][t]` (price-based scheduled charging); a slot may have either, not both (constraint), so cheap-hour charging and surplus charging never double-count. Schedule output (`planner/output/formatter.py`) gains per-slot `ev_surplus_kw` per charger; a nonzero value marks the slot surplus-eligible for the executor. *Alternative rejected:* reusing the binary `ev_charge` at nominal power — surplus is inherently fractional (2–10 kW range), and binary-at-nominal would make the solver refuse small surpluses entirely.

### D3. Executor tracks measured surplus with a feedback loop, bounded by plan eligibility
Within a surplus-eligible slot, each tick the executor computes the live surplus signal from `SystemState`: export power (dual meters) or negative grid power (net meter). Feedback: if `export_kw > deadband` → raise the EV setpoint by the export equivalent in amps (subject to Change 1's increase-slow ramp); if importing beyond the deadband → lower it immediately. The planner's `ev_surplus_kw` acts as eligibility, not a hard target — clouds make the 15-min number stale within seconds. Ordering: surplus tracking proposes a setpoint → Change 1's balancer caps it → dispatch. In slots with no surplus eligibility, EV control behaves exactly as scheduled charging (Change 1). Deadband is a config key (default 0.2 kW). *Alternative rejected:* executing the planned kW open-loop — imports grid power the moment a cloud passes, which is precisely the "charge from surplus only" promise broken.

### D4. Sustained-shortfall pause reuses Change 1's floor/pause machinery
When the feedback loop pushes the setpoint below the effective minimum (6 A × active phases) and phase switching cannot rescue it (already 1-phase, or switching unavailable), the EV pauses — same pause primitive, resume delay, and resume margin as Change 1's balancer, with surplus-specific resume condition (measured surplus ≥ 1-phase minimum + margin for the delay period). No new anti-flap mechanism is invented.

### D5. Phase switching is a threshold state machine owned by the executor, with dwell-time protection
For chargers with `phase_mode_entity` configured and `phase_switching.enabled`: target power below `(3ph_min + hysteresis_kw)` for the whole dwell window → command 1-phase; target power above it (and 3-phase useful) → command 3-phase. A `min_dwell_s` (default 600 s) lockout between switches protects the contactor and rides out cloud flicker; the go-e side pause during switching is tolerated (seconds). The kW→A conversion and the 6 A floor always use the *commanded* phase count, cross-checked against the charger's measured per-phase draw (Change 1 D4) — a car that only charges 1-phase regardless makes 3-phase mode pointless, and measurement catches that. Fail-safe: if the phase-mode entity is unreadable or the write fails, no further switching is attempted (state = unknown → assume configured `phases`), charging continues at whatever mode the charger is in. *Alternative rejected:* letting the go-e's native auto phase switching (`psh`/`spl3`) handle it — Darkstar is the single decision-maker (user requirement), and mixing two controllers arguing over phase mode invites oscillation.

### D6. Config shape: ordered array with per-entry type, replacing the `sink` enum
`executor.excess_pv.priority[]` — ordered list of `{type: ev | water_heater_boost | custom_entity, ...per-type fields}` (EV entries reference `ev_chargers[].id`; custom-entity entries carry the existing entity/on/off/power fields; multiple custom entities become possible for free). Shared keys (`soc_threshold_percent`, `boost_reward_sek_per_kwh`) stay at the `excess_pv` level. Phase-switching keys live on the charger device (`ev_chargers[]`: `phase_mode_entity`, `phase_switching: {enabled, hysteresis_kw, min_dwell_s}`) since they are charger properties, not dispatch properties. Migration (`backend/config_migration.py`): `sink: water_heater_boost` → `priority: [{type: water_heater_boost}]`, `sink: custom_entity` → one-element array carrying over the custom-entity block, `sink: disabled` → `priority: []`; the old key is dropped. `ExcessPVSinkType`/`ExcessPVConfig` in `executor/config.py` are reshaped accordingly.

### D7. UI: priority-list editor in the existing Advanced tab section
The "Excess PV Dispatch" section becomes: global list with add/remove/reorder (up/down buttons are sufficient — no drag-and-drop dependency), one collapsible panel per entry with its per-type fields, shared threshold/reward fields below, and phase-switching fields on the EV charger's device settings. Sink availability rules carry over (no water-heater option when `has_water_heater=false`; EV option only when a `current`-type charger exists). Live "what surplus is doing right now" indicators ride on Change 1's status surface (balancer/EV state is already being added there); this change adds the surplus-mode fields to that payload rather than building a second status channel.

## Risks / Trade-offs

- [Cloud flicker causes amp sawtooth / phase-mode thrash] → deadband + increase-slow ramp for amps; hysteresis + 600 s dwell for phase mode; pause/resume uses Change 1's delay+margin. Worst case is suboptimal harvest, never fuse risk (balancer caps independently).
- [Rank-scaled rewards could invert user intent if a per-sink override exceeds a higher rank's reward] → validation warns when overrides break monotonicity; defaults never do.
- [Solver runtime grows (continuous var + exclusivity constraint per charger per slot)] → variables are created only for plugged-in current-type chargers in flagged slots (same trick as existing sinks); benchmark scripts (`scripts/benchmark_solver.py`) gate regressions.
- [Executor surplus signal wrong for net-meter users (sign conventions)] → reuse existing normalized `SystemState` import/export fields rather than raw sensors; covered by unit tests with both meter types.
- [Phase switch mid-charge annoys some cars (charging interruption)] → dwell time bounds frequency; switching only when the power delta actually matters (hysteresis); documented per-charger disable flag.
- [Change 1 slips or its interfaces drift] → this change consumes only Change 1's declared config fields and actuation/anti-flap primitives; tasks reference them by name so drift surfaces at review, and implementation order is enforced (this change blocks on Change 1's completion).
- [Legacy single-sink configs in the wild] → automatic migration with log line; `priority: []` behaves exactly like `sink: disabled`.

## Migration Plan

1. Land after `universal-load-balancing` is implemented and verified.
2. Config migration runs at startup: `excess_pv.sink` → `excess_pv.priority[]` (idempotent, logged); defaults keep new features off (`priority` empty or without an EV entry; `phase_switching.enabled: false`).
3. Planner/solver changes are inert while no EV entry exists in `priority[]`; executor surplus path is inert while the schedule contains no `ev_surplus_kw`.
4. User enables: adds the EV entry to the priority list, orders it, configures `phase_mode_entity` once the charger is installed, flips `phase_switching.enabled`.
5. Rollback: remove the EV entry / restore a single-sink-equivalent priority array; no data migration to undo (schedule fields are additive).

## Open Questions

- None blocking. go-e entity IDs (current, phase mode) are configured after hardware installation. Exact reward decrement (0.15/rank) is a tunable default; adjust during verification against real solver output.
