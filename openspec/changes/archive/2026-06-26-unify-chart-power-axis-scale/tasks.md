## 1. Unify the power axis scale

- [x] 1.1 In the chart-init scales block (~line 1227–1239), set `y4.max` to `Math.max(scaling.gridMaxKw, scaling.inverterMaxKw, scaling.solarKwp)`, and update `y1.max`/`y2.max` to use the same expression
- [x] 1.2 In the dynamic scale-update effect (~line 1294–1313), fold `scaling.solarKwp` into the computed shared max and apply it to `y1`, `y2`, and `y4`
- [x] 1.3 Update the static default `y4.max` (and `y1`/`y2` defaults if needed) so the pre-data placeholder scaling is consistent and avoids a mismatched flash before real data loads

## 2. Verify

- [x] 2.1 Confirm a bar and the PV line at the same kW render at the same height, and that PV peaks above the grid/inverter limit no longer clip
- [x] 2.2 Confirm runtime scaling-config changes update all three power axes (`y1`, `y2`, `y4`) to the same shared max
- [x] 2.3 Confirm the price axis (`y`), SOC axis (`y3`), and non-power series are unaffected
- [x] 2.4 Run frontend lint/typecheck and any existing ChartCard tests
