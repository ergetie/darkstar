# Tasks: risk-aware-safety-buffer-cap

## 1. Core Implementation (`planner/strategy/s_index.py`)

- [x] 1.1 Add `cap_scale` to each `RISK_CONFIG` entry: 1 → 1.50, 2 → 1.25, 3 → 1.00, 4 → 0.85, 5 → 0.75 (update the adjacent comment block accordingly)
- [x] 1.2 Compute the effective cap: `max_buffer_kwh = capacity_kwh * max_safety_buffer_pct * cap_scale`, then floor it at the risk level's minimum buffer: `max_buffer_kwh = max(max_buffer_kwh, min_buffer_kwh)`
- [x] 1.3 Add `cap_scale` to the S-Index debug dict (keep `max_buffer_kwh` as the effective post-scaling, post-floor value)
- [x] 1.4 Verify the Layer 2 price addon path is untouched (still applied after the cap, still bounded at 80% of capacity)

## 2. Config Comments

- [x] 2.1 Update the `max_safety_buffer_percent` comment in `config.default.yaml`: state it is the Risk 3 (Neutral) baseline scaled per risk level, and remove the stale "(default 40%)" tail
- [x] 2.2 Apply the same comment fix in `config.yaml`

## 3. Tests

- [x] 3.1 Update existing cap assertions in `tests/planner/test_safety_floor_temporal.py` and `tests/planner/strategy/test_s_index_new.py` to the per-risk effective cap (Risk 3 cases must be numerically unchanged)
- [x] 3.2 Add test: under a saturating deficit with config = 20, floors are strictly ordered Risk 1 > Risk 3 > Risk 5, and Risk 3 equals min_soc + 20% of capacity
- [x] 3.3 Add test: Risk 1 with `max_safety_buffer_percent = 10` still honors the 25% minimum buffer (cap floored at min_buffer)
- [x] 3.4 Add test: debug payload contains `cap_scale` and the effective `max_buffer_kwh`
- [x] 3.5 Check `tests/planner/strategy/test_s_index_price_awareness.py` for fixtures that hard-code the flat 20% cap; adjust if needed

## 4. Verification

- [x] 4.1 Run the full planner/strategy test suite (`pytest tests/planner`) — all green
- [x] 4.2 Sanity-run the S-Index calculation at all five risk levels with a saturating-deficit fixture and confirm the debug output shows five distinct effective caps
