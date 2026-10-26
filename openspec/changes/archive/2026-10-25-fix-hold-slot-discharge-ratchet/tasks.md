## 1. Executor

- [x] 1.1 In `executor/controller.py` hold branch of `_follow_plan` (L287-293): call `self.plan_state.enter(None, None)`, set `mode_intent = "idle"` and `note = HOLD_REASON`; update the branch comment. Keep branch order (both isolation branches first); update the branch comment and the stale 'hold margin' mention in the `ev_isolating` branch comment (L283).
- [x] 1.2 Delete `_hold_mode`; replace `HOLD_MARGIN_REASON` with `HOLD_REASON = "hold slot, blocking battery discharge"`.
- [x] 1.3 Update comments: `SOC_TRACKING_MARGIN` (L30-34; charge resume and min-SoC guard only), `BatteryPlanState` docstring and `kind` comment (charge only, `latched` is the charge latch), `executor/config.py` L354 (`min_soc_percent` no longer bounds a hold margin), `executor/override.py` L133 and `executor/engine.py` L1931 wording.
- [x] 1.4 Verify `executor/engine.py` plan_state handling (L424, L604, L1965) needs no change; grep for any other `"hold"` kind, `HOLD_MARGIN_REASON` or `_hold_mode` use (expected none).

## 2. Tests (`tests/executor/test_battery_plan_tracking.py`)

- [x] 2.1 Replace `TestHoldMargin` and `TestHoldFloorAtMinSoc` with hold-always-idle tests: any SoC (60, 50, 49, 40), reason is `HOLD_REASON`, stable across 49/50 alternation, hold at/below min SoC idles with no charge write, no state left in `plan_state` after a hold tick.
- [x] 2.2 Keep and adapt: EV isolation and keep-on precedence, `discharge_blocked_by_ev` slot has no hold reason, discharge slot at floor still idles at floor and self-consumes above it.
- [x] 2.3 Add regression test reproducing the ratchet: one controller, successive hold plans with targets 96, 94, 92, 90 and live SoC equal to each target (also 1-2 points above); assert every decision is `idle` and the mode never flips.
- [x] 2.4 Add test: a hold slot after a stopped grid-charge block resets the charge latch (later charge block resumes charging).
- [x] 2.5 Add test that min-SoC guard still updates and persists through a hold block, and releases only at `min_soc + 2` for a following self-consumption slot.
- [x] 2.6 Add a profile test over `profiles/*.yaml` (fronius, deye, sungrow; generic and schema template) asserting `modes.idle` writes no zero value to a charge-limit entity (`max_charge_current`, `max_charge_power`).
- [x] 2.7 Run `UV_NO_SYNC=1 uv run python -m pytest tests/executor -q` and fix any other test that assumed `self_consumption` in a hold slot (check `tests/executor/test_ev_isolation.py`, `test_executor_controller.py`).

## 3. Verify

- [x] 3.1 `./scripts/lint.sh`.
- [x] 3.2 No edits to `docs/` or `docs/RELEASE_NOTES.md`; no commit or push unless instructed.
