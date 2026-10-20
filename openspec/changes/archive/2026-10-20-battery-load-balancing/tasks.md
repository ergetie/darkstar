# Tasks

## 1. Config

- [x] 1.1 Accept `kind: battery` in `_parse_load_balancing_config` (`executor/config.py`): normalise id to `battery`, drop duplicates with a warning, and update the `GiveWayOrderEntry` docstring
- [x] 1.2 Extend `heal_give_way_order` with a `battery_available` argument (profile loaded with a `charge` mode): keep or drop the battery entry, or append it at the end; update callers (config load about line 656, `_run_load_balancer`)
- [x] 1.3 Add a commented battery give-way example to `config.default.yaml`; check any give-way kind validation in `backend/api/routers/config.py`
- [x] 1.4 Unit tests for parsing and heal placement

## 2. Balancer core

- [x] 2.1 Add `BatteryBalancerInput` (fixed phases [1, 2, 3], planned_w, applied_cap_w, reducible_w, active, min_w, stale flags) and `BatteryBalancerOutput` (cap_w, state, reason) to `executor/load_balancer.py`; add `battery_output` to `LoadBalancerStatus`
- [x] 2.2 Give-way pass: cut the battery by the remaining deficit (`deficit × V × 3`, limited to `reducible_w`, clamped to `[0, planned_w]`), fold relief into `pool_headroom`, and mark `pending_relief_phases` for entries below
- [x] 2.3 Ramp/restore: `ramp_up_window_s` hold-off, averaged `target_margin_percent` gate, `increase_step_a` per phase, paused restore after `resume_confirm_s`, and blocking of restores above it in the reverse pass
- [x] 2.4 Stale handling: hold the cap on any stale battery phase
- [x] 2.5 Overall state/reason aggregation includes the battery
- [x] 2.6 Unit tests: the reported 20 A / 24 A scenario, single-phase overload spread over 3 phases, entry above absorbs the deficit, non-charge intent ignored, zero import ignored, ramp back, stale hold, ordering vs shed and chargers

## 3. Engine integration

- [x] 3.1 `_run_load_balancer`: build the battery input from the decision (`mode_intent`, `charge_value` converted to W per `control_unit`), `current_import_kw`, and `battery_power`; insert it at its `give_way_order` position (this needs the decision passed in)
- [x] 3.2 Apply the cap to `decision.charge_value` before `dispatcher.execute(decision)`: round down to the profile step in A or W, and switch to `idle` below the profile minimum, with a reason in `last_action`
- [x] 3.3 `_track_balancer_throttling`: track key `battery` against planned_w and fire the rate-limited replan; ensure `_notify_balancer_interventions` skips the battery (test)
- [x] 3.4 `get_load_balancer_status`: add the `battery` object (additive)
- [x] 3.5 Engine tests for Deye (A, 48 V, round 5 A, min 10 A) and Fronius (W) cap application, idle fallback, and replan trigger

## 4. Frontend

- [x] 4.1 `giveWayOrder.ts`: add the `'battery'` kind and the heal mirror (append at end when available); tests
- [x] 4.2 `GiveWayListEditor.tsx` / `LoadBalancingTab.tsx`: render the "House battery (grid charging)" entry per `docs/design-system/AI_GUIDELINES.md`; tests
- [x] 4.3 `frontend/src/lib/api.ts` types and battery row in `LoadBalancerStatusCard.tsx` / `LoadBalancerCompactView.tsx`; tests
- [x] 4.4 Settings search aliases/glossary entries for the battery give-way

## 5. Verification

- [x] 5.1 Run `./scripts/lint.sh` and the full test suites
