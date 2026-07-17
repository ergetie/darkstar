# Design: keep-on-slot-flag

## Context

`_apply_keep_on_after_target` (planner/pipeline.py:238-293) runs after the Kepler solve and, for every future slot of a charger whose target is met with `keep_on_after_target: true`, injects `slot.ev_charger_results[charger_id] = max_kw` and recomputes `slot.ev_charge_kw`. It deliberately does NOT touch `grid_import_kwh`/`cost_sek`/SoC — keep-on is a switch-state intent (cabin pre-conditioning), not planned energy. The fake power was chosen because the executor's only "should this charger be on?" signal is `plan_kw > 0.1`.

The full reader map was investigated 2026-07-11 (recorded in this design; also in project memory `project-real-fixes-investigations`). The serialized fields are `ev_charging_kw` (aggregate) and `ev_chargers` (per-charger dict) in `data/schedule.json`, produced via `planner/solver/adapter.py:kepler_result_to_dataframe` (lines 606-607) and `planner/output/formatter.py`.

**Executor decision sites reading plan power (all must become flag-aware):**

| Site | Role |
|---|---|
| `executor/engine.py:2958-2959` `_control_ev_charger` | switch-close decision (`should_charge = plan_kw > 0.1`) |
| `executor/engine.py:2637-2645` `_run_load_balancer` | current-type chargers: `planner_target_a = None` when plan kW is 0 → charger never commanded |
| `executor/engine.py:2526-2527` `_run_ev_surplus_and_phase` | 1-/3-phase mode target power |
| `executor/engine.py:1340-1377` tick | battery source isolation trigger (`scheduled_ev_charging`) |
| `executor/controller.py:202` `_follow_plan` | secondary isolation: forces `idle` instead of `self_consumption` |

Supporting sites: `_parse_slot_plan` (engine.py:1902-1919, includes aggregate→first-charger backward-compat fallback at 1916-1919), `SlotPlan` dataclass (executor/override.py:100-103), `get_status` (engine.py:440-475), execution record (engine.py:2293). `set_ev_charger_switch`'s `charging_kw` parameter is logging-only (executor/actions.py:1088-1097).

Frontend readers: `ChartCard.tsx:1729-1730` (EV bar series), `Executor.tsx:1019` (current-slot badge), `Executor.tsx:1077` (history badge), `frontend/src/lib/types.ts:12` (`ScheduleSlot`).

Tests: `tests/planner/test_keep_on_after_target.py` (6 tests assert the fake 11.0 kW). No test today drives a keep-on slot through the executor switch path — untested guarantee.

User decisions already made (2026-07-12): honest flag, no standby-draw estimates; history via reason text only (no DB migration); chart shows a thin "EV standby" band; Executor page shows an "EV standby" badge variant.

## Goals / Non-Goals

**Goals:**
- Published schedules are energy-consistent: keep-on slots carry 0 planned kW plus an explicit per-charger flag.
- Keep-on behavior (switch held on through ready-by) is preserved for binary AND current-type chargers.
- Battery source isolation remains active during keep-on slots, including before the car starts drawing.
- The user can always see keep-on state (chart band, executor badges).
- The switch-closes-on-keep-on guarantee gets test coverage at the executor level.

**Non-Goals:**
- No standby-power estimation or energy-balance folding (rejected by user).
- No `execution_log` DB schema change (reason text only).
- No change to the keep-on *eligibility* logic (when a charger qualifies) — only its representation.
- No changes to learning/observation recording (`ev_charging_kwh` measured field is unrelated).
- No HA actuation changes.

## Decisions

### D1: Flag shape — per-charger dict `ev_keep_on: dict[str, bool]`, serialized as `ev_keep_on: {charger_id: true}`

Mirrors the existing per-charger `ev_chargers: {charger_id: kw}` pattern exactly (same adapter/formatter/parser path, multi-charger-correct from day one). Only chargers in keep-on state appear in the dict; absent key or empty dict means no keep-on. Alternative rejected: a slot-level boolean — ambiguous with several chargers.

### D2: Pipeline placement — same function, write flag instead of power

`_apply_keep_on_after_target` keeps its position and eligibility logic; the mutation body changes from power injection to `slot.ev_keep_on[charger_id] = True` (new field on `KeplerResultSlot`, default empty dict via `field(default_factory=dict)`). `ev_charger_results`/`ev_charge_kw` are left untouched (solver output, which is 0 for post-target slots). Adapter adds an `ev_keep_on` column; formatter passes it through like `ev_chargers` (normalize non-dict → `{}`).

### D3: Executor — one helper, used at all decision sites

Add `SlotPlan.ev_keep_on: dict[str, bool]` (default empty). In `_parse_slot_plan`, read `slot_data.get("ev_keep_on")`. Introduce one private helper on the engine, e.g. `_charger_should_be_on(slot, charger_id) -> bool` ≡ `plan_kw > 0.1 or slot.ev_keep_on.get(charger_id, False)`, and use it at the three decision sites (2958, 2637, 2526) so the rule can never diverge again. For current-type chargers in keep-on with 0 planned kW, the load balancer's `planner_target_a` uses the charger's configured minimum current (`charger_cfg.min_current_a` — a per-charger config value, not a hardcoded 6) rather than a computed target — enough to hold the relay closed while the full car draws ~nothing; the balancer may still throttle it like any other demand.

Rationale for minimum current over max: keep-on plans no energy, so requesting max amps would misrepresent demand to the load balancer and steal headroom from real consumers.

### D4: Isolation — flag counts as "scheduled EV charging"

`scheduled_ev_charging` in `tick` (engine.py:1340-1377) and the `_follow_plan` check (controller.py:202) treat "any keep-on flag set on the current slot" the same as planned power > 0.1. This preserves the pre-draw isolation window deliberately: the user does not want the house battery feeding the EV, and during keep-on the car may start drawing at any moment.

### D5: Backward compatibility — additive only, no fallback synthesis for the flag

The aggregate fallback (engine.py:1916-1919) synthesizes per-charger plans from `ev_charging_kw` for old-format schedules; those old schedules encode keep-on as fake power, so the fallback keeps working unchanged for them. New-format schedules carry the flag explicitly. The only degraded window is a pre-change schedule surviving a deploy boundary in the opposite direction (new schedule read by old executor: flag ignored, keep-on lost until next plan) — accepted, self-heals within one planner cycle.

### D6: Surfacing — status API, reason text, frontend

- `get_status` includes `ev_keep_on` in `current_slot_plan` (additive key).
- Tick reason text appends a keep-on note (e.g. "EV keep-on active: <ids>") when the flag drives the decision; `ExecutionRecord`/DB untouched.
- Frontend `ScheduleSlot` gains `ev_keep_on?: Record<string, boolean>`. ChartCard: when a slot has 0 EV kW but any keep-on flag, render a thin fixed-height "EV standby" band at the chart bottom (own legend entry + tooltip "Charger switch held on after target — car draws only what it needs"). Executor page: badge "🔌 EV standby" when `ev_charging_kw ≤ 0.1` but keep-on present (current slot from status API; history rows use the reason text as the signal, since the DB has no flag column).

### D7: Tests

Rewrite the 6 planner tests to assert 0 kW + flag. Add executor tests: (a) binary charger — switch commanded ON for a slot with `ev_keep_on` set and 0 planned kW; (b) current-type charger — load balancer receives the minimum-current target; (c) isolation — battery discharge blocked during a keep-on slot with no measured EV draw.

## Risks / Trade-offs

- [Missed reader] A plan-power consumer not on the investigated map silently changes behavior → the reader map was built exhaustively (2026-07-11) including false-positive elimination; full test suite + the new executor tests gate the change.
- [Current-type keep-on semantics] Holding 6 A minimum reserves a little phase headroom for a car that draws nothing → acceptable: it is the smallest representable "on" state, and the balancer can still shed it under fuse stress.
- [History badge heuristic] History rows infer standby from reason text, which is weaker than a structured field → accepted as KISS per user decision; revisit only if audit questions actually arise.
- [Deploy-boundary loss of keep-on] New schedule + old executor loses keep-on for ≤1 planner cycle → accepted, self-healing, no fuse/safety implication (failure mode is "switch off", the safe direction).

## Migration Plan

Additive schema, no migration. Deploy backend+frontend together as usual; first post-deploy planner run writes the new field. Rollback: revert the change — old code ignores the extra JSON key.

## Open Questions

_None — all decisions resolved with the user (flag shape, no standby estimate, KISS history, standby visuals)._
