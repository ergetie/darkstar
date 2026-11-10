## Why

Aurora's load forecast is systematically too low and flat on some sites (user report, Nov 2026: whole-day about -15 %, evening 15-21 about -21 %). Walk-forward backtests on four sites (maintainer about 1 year, PLL Feb-Nov, Kristofer May-Oct, reporter Oct) found three fixable causes and one cheap, robust post-model fix:

- Fake training rows. `_load_slot_observations` (`ml/train.py:153-172`) filters only `load_kwh > 0.001`, the `max_kwh` caps and `"exclude": true`. The pre-`453e1095` legacy recorder subtracted EV and clamped load at 0, leaving whole days with near-zero load while import, PV or battery discharge is clearly active (reporter's Jul-Aug days about 3 kWh/day against a real 28). Such rows teach the model a low, flat load.
- No level input. Load features are calendar, weather and context flags only (`ml/train.py:257-279`, `ml/forward.py:408-420`).
- A median model alone stays biased low on quiet/changing sites. Averaging model models swung +14 to +36 % in quiet months, so the model stays median and a bounded blend with the recent same-slot mean is applied after it.
- A dead setting, `forecasting.load_safety_margin_percent`, misleads users; nothing reads it.

Weather history is already fixed: commit `1d1f14a5` (2026-11-04, after tag `v2.7.1-beta`, unreleased) makes `train_models` use `ml.weather.get_historical_weather_series` (`ml/weather.py:548`). The `past_days=1` call (`ml/weather.py:424-430`) is the live inference path and unchanged. Only a regression test is added.

## What Changes

- Training data rule (universal): drop legacy backfill rows (`source: backfill` without `recording` provenance) and drop whole legacy (non-`recording`) local days with a clamp signature. Everything else is kept, including long good legacy history. Dropped counts are logged and stored in `learning_runs` metrics.
- New load-only feature `load_level_7d` (mean daily load of the previous 7 clean local days).
- Post-model blend of the load middle forecast: `final = 0.4 x model p50 + 0.6 x slot_mean_7d`, constants in code, p10/p90 shifted by the same delta.
- Load model schema bump; models rejected for schema mismatch trigger an automatic retrain.
- **BREAKING (config):** remove the dead `forecasting.load_safety_margin_percent` and `learning.max_daily_param_change.load_safety_margin_percent` keys (defaults, settings UI, search guide, help text) with a config migration that drops them from existing `config.yaml`.
- Manual operational step after release: the maintainer runs `scripts/flag_january_bad_slots.py` on their production DB (requires explicit user approval).

Backtest evidence for the blend (weekly retrain, year-long): day bias maintainer -10.4 % -> -4.4 %, PLL -5.2 -> -1.2, Kristofer -13.3 -> -4.6; evening, RMSE, daily abs error and 3 h/6 h block energy better on all sites; MAE within about 1 %. The clamp rule flagged 74 of 76 reporter fake days, 2 true fake days on Kristofer, 0 on maintainer (max share 0.281) and PLL (max 0.167).

## Capabilities

### New Capabilities
- `load-training-data-quality`: which rows/days load training may use, clamp detector, reporting.
- `load-level-feature`: `load_level_7d`, missing-data behavior, schema versioning and automatic retrain.
- `load-slot-blend`: post-model blend, fallback, band consistency.
- `config-dead-key-removal`: removal of the dead load safety margin setting.

### Modified Capabilities
None (existing `pv-training-weather-history` already covers weather).

## Impact

- Code: `ml/train.py`, `ml/forward.py`, new `ml/load_clean.py` (clamp detector, slot means, level), `backend/config_migration.py`, `config.default.yaml`, `samples/config.sample.json`, `frontend/src/pages/settings/types.ts`, `frontend/src/pages/settings/search/guides.ts`, `frontend/src/config-help.json`, scheduler retrain hook.
- No DB schema change and no rewrite of stored rows. Existing load models are retrained once.
- Out of scope: PV changes, L2/average models, per-site model selection, `docs/`.
