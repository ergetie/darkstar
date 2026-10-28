## 1. Executor

- [x] 1.1 In `executor/engine.py` boost branch (~1751-1790), remove the `min_boost_soc` calculation, the low-SoC `if`, `_water_boost_until.clear()`, warning log and notification; always build the FORCE_HEAT override
- [x] 1.2 Set override `soc_target` to `slot.soc_target` (current plan slot, as EV isolation/hold slots use, engine.py ~620); if `slot` is None use `max(round(SoC), int(min_soc_percent))`; update the stale comment
- [x] 1.3 Verify `_apply_override` needs no change (idle, zero discharge, no discharge write)

## 2. Tests (`tests/executor/test_executor_engine.py`)

- [x] 2.1 Delete `test_boost_cancelled_notification_is_awaited`
- [x] 2.2 Add: boost at SoC 5 / min_soc 10 stays active after `run_once` and produces a FORCE_HEAT override, no notification sent
- [x] 2.3 Add: boost decision is `idle`, discharge_value 0, no discharge write, at SoC 5 and at SoC 50
- [x] 2.4 Add: override `soc_target == slot.soc_target` at SoC 5 and 50; without a plan slot it equals `max(round(SoC), min_soc_percent)`
- [x] 2.5 Add (controller level): boost override with `min_soc_guard` latched still returns idle override
- [x] 2.6 All tests use a frozen clock on a fixed non-DST date (e.g. 2026-06-15) and a 96 quarter-hour slot schedule

## 3. Verify

- [x] 3.1 `UV_NO_SYNC=1 uv run python -m pytest tests/executor -v`
- [x] 3.2 `./scripts/lint.sh`
