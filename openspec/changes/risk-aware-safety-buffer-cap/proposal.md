# Proposal: risk-aware-safety-buffer-cap

## Why

The safety-floor cap (`max_safety_buffer_percent`, default 20% of battery capacity) is applied identically at every risk level, which silently defeats the user-facing `risk_appetite` setting. Two concrete failures:

1. **Risk 1 (Safety) is broken every day, not just hard days:** `RISK_CONFIG` promises Risk 1 a minimum buffer of 25% of capacity, but the 20% cap always wins — a Safety user *never* receives the reserve their setting promises, even on easy days.
2. **Differentiation collapses on high-deficit days:** on moderate-to-hard days, Risk 1–3 users all hit the same 20% ceiling, so the risk slider has no effect exactly when it matters most.

## What Changes

- Make the safety-floor cap risk-aware: each risk level gets its own effective cap, derived by scaling the configured `max_safety_buffer_percent` with a per-risk multiplier (Risk 1 highest ceiling, Risk 5 lowest). The configured value remains the Risk 3 (Neutral) baseline, so existing configs keep their current meaning for neutral users.
- Guarantee internal consistency: the effective cap at each risk level is at least that level's `min_buffer_pct`, so a risk level's promised minimum buffer can never be suppressed by its own cap.
- Surface the effective (post-scaling) cap in the S-Index debug output so run history shows which ceiling actually applied.
- Update the existing safety-floor tests and add coverage for per-risk cap differentiation.
- **Behavior change (intended):** Risk 1 and 2 users will hold a higher reserve on high-deficit days (more grid charging, less aggressive optimization); Risk 4 and 5 users get a slightly lower ceiling. Risk 3 behavior is unchanged.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `planner`: The Temporal Safety Floor requirement changes — the `max_safety_buffer_pct` cap SHALL be scaled per risk level instead of being a single risk-independent ceiling, and SHALL never fall below the risk level's minimum floor.

## Impact

- **Code:** `planner/strategy/s_index.py` (cap application in the temporal safety-floor calculation, `RISK_CONFIG` table, debug dict).
- **Config:** `max_safety_buffer_percent` keeps its existing key and semantics as the Neutral baseline — no config migration needed. `config.default.yaml` comment updated to describe the per-risk scaling.
- **Tests:** `tests/planner/test_safety_floor_temporal.py`, `tests/planner/strategy/test_s_index_new.py` (cap-related cases), possible touch-points in `test_s_index_price_awareness.py` (the price addon bypasses this cap by design — verify that stays true).
- **UI:** None — the setting is config-file-only and the S-Index debug/run-history payload is additive.
- **Users:** Cautious (Risk 1–2) users see higher floors on hard days; Gambler (Risk 4–5) users see slightly lower ceilings. Neutral users unaffected.
