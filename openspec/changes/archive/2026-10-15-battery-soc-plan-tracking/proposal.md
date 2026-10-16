## Why

The executor follows the battery plan too literally, and too long after it stopped matching reality. Three Discord reports (2026-10-12/13) show the cost:

- torleif: the battery dropped to 3% under heavy load, then grid-charged to 18% and kept charging ~30 more minutes until a manual replan. Earlier a stale plan charged at 17% and then idled. Darkstar never stops grid charging at the planned level (only some inverter profiles do on their own), and nothing replans when the battery drifts from the plan; only the periodic run (30 min) does.
- Kristofer: with the solar forecast too high, the inverter flips between auto and block-discharge while electricity is expensive. In a hold slot the executor blocks at or below the target and returns to auto above it, with no margin, so a 1% change flips the mode.
- youask (old version): similar grid buying on a day with a far-too-high PV forecast.

The underlying PV over-forecast is tracked separately (backlog: "Systematic PV Over-Forecast"). An intraday PV correction was evaluated on production data and rejected for now (10–25% less error, worse in ~25% of cases).

## What Changes

- Grid charging stops for the rest of a charge block once live SoC reaches the block's planned target; it resumes in that block only if SoC falls 2 points below the target.
- Hold slots get a margin: the battery may cover load down to 2 points below the hold target before discharge is blocked, and the block lifts again only once SoC is back at the target. No more flipping on a 1% change.
- The executor requests an immediate replan when live SoC deviates from the plan's expected SoC by more than a threshold for 5 minutes, at most once per 15 minutes. New reason `soc_deviation`.
- New setting `executor.soc_deviation_replan_percent` (default 10, 0 disables), shown in the settings UI.
- Tick reasons and the execution log say why the executor held or stopped charging.

## Capabilities

### New Capabilities

- `battery-plan-tracking`: how the executor keeps the battery consistent with the plan at runtime (stop grid charging at target, hold margin, replan on SoC deviation).

### Modified Capabilities

None.

## Impact

- Executor: `executor/controller.py` (charge and hold mode selection), `executor/engine.py` (per-block latch, hold margin state, deviation tracking, replan request), `executor/config.py` (new key).
- Backend: `backend/services/scheduler_service.py` (`ReplanReason.SOC_DEVIATION`).
- Config: `config.default.yaml` (new key with comment).
- Frontend: settings field in `frontend/src/pages/settings/types.ts` and settings search guide.
- Tests: `tests/executor/`, `tests/backend/` as needed, settings frontend tests.
- Inverter profiles are unchanged.
