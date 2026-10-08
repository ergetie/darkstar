## 1. Per-slot accounting

- [x] 1.1 Add a focused pure grid-only accounting helper with isolated household + water + EV demand, recorded import/export prices, gross measured DS flows, signed bill difference, and response-only rounding.
- [x] 1.2 Implement relevant-input eligibility and UTC completed-slot coverage: reject missing/invalid values, placeholders, exclusions, backfills and known snapshot/mixed essential readings; allow valid legacy recorder rows; require configured-battery charge/discharge readings and provenance, while no-battery systems ignore battery flows.
- [x] 1.3 Add meaningful calculation tests for varying slot prices versus averages, EV/water counted once, gross simultaneous import/export, zero/negative tariffs, battery charging omitted from baseline demand, configured wear included once on DS, and stored-energy valuation excluded.
- [x] 1.4 Add coverage/aggregation tests for missing hours without anchor-slot loss, incomplete/future slots, no-data/all-invalid periods, repeated DST hours, 92/100-slot days, maximal covered segments with slot-boundary cumulative points, gaps within hourly/daily buckets, continuity across bucket/DST boundaries, and bucket/segment/summary reconciliation.

## 2. Energy API replacement

- [x] 2.1 Update `/api/energy/cost-series` to query the selected period, preserve top-level actual started-slot accounting, and return the specified `grid_only_comparison` summaries, bucket bounds/points, covered segments with cumulative slot-boundary points, through-time, statuses/reasons, coverage and full-period `time_axis` metadata for every valid status.
- [x] 2.2 Remove legacy `baseline`, per-point `baseline_*`, `battery_comparison`, self-use replay, calibration-history/preceding-SoC queries and router fit/cache work; inspect imports before deleting helpers and preserve independently used history-audit modules.
- [x] 2.3 Replace retired financial API/cache tests with contract tests proving DS electricity and configured wear reconcile to wear-inclusive DS cost and saving, partial/no-data/unavailable behavior, exact within-bucket gap segments, full 23/25-hour DST axis bounds even without comparison amounts, solar-only/grid-only support, no-battery flow independence, configured-battery missing-flow exclusion, and unchanged actual range/today/wear totals.
- [x] 2.4 Verify the new request path performs no self-use simulation, calibration, wide historical scan or planner run, and makes no writes to observations, annotations, configuration or runtime databases.

## 3. Financial card and chart

- [x] 3.1 Replace retired API types and all bundled consumers with explicit grid-only comparison, covered-segment and time-axis types, distinguishing amount-bearing from unavailable responses and rejecting malformed amounts, points, segment bounds/order or axis metadata.
- [x] 3.2 Replace the comparison line with signed **DS vs grid-only** amounts including DS wear and zero grid-only wear, with neutral zero styling; keep actual electricity and separate wear figures, partial coverage suffix, and accessible bill-details panel with the exact explanation, component amounts, local through-time and slot counts.
- [x] 3.3 Remove the Self-Use Saved row/tooltip, Estimate/Verified/calibration/inventory UI details and legacy fallbacks; identify Battery Charge as informational and already included in Grid Import, display concise unavailable reasons, and support installations without batteries.
- [x] 3.4 Update chart geometry to draw directly priced DS/Grid-only cumulative segment boundary points and eligible bucket bars; position comparison and Actual-only charts by elapsed UTC time within the supplied full-period bounds, use installation-local labels/readouts, allow 23/25-hour days and distinguish repeated hours by position/UTC offset; preserve the common zero-inclusive scale, hourly/daily bars, interactions, and reduced-motion behavior.
- [x] 3.5 Draw each covered segment independently: break both lines and shading across excluded slots even within hourly/daily buckets, carry cumulative totals into the next segment without connecting across gaps, split shading at covered crossings, and reconcile bucket readouts and segment endpoints with summaries.
- [x] 3.6 Update card/chart behavior and geometry tests for signed/zero wear-inclusive amounts, electricity/wear reconciliation, exact details and dismissal, partial/unavailable data, solar-only installations, direct grid-only values, matched coverage, crossings, within-bucket gaps, 23/25-hour DST axes, distinct repeated-hour positions/offset labels, browser versus installation timezone differences, Actual-only time-axis behavior and unchanged actual wear display.
- [x] 3.7 Update `/design-system` financial fixtures to complete, negative, partial, unavailable, within-bucket gap and fall-back DST grid-only examples with wear-inclusive DS values using existing tokens/components without editing the `docs/` directory.

## 4. Verification

- [x] 4.1 Run focused backend financial tests plus history/provenance regressions to confirm preserved audit tooling and unchanged recorded-data handling.
- [x] 4.2 Run focused frontend financial card/chart tests and the frontend type/build checks appropriate to the changed API contract.
- [x] 4.3 Verify the card, info panel, chart and comparison labels at mobile/desktop sizes in light/dark themes; check partial/empty results, within-bucket gap breaks, 23/25-hour DST axes and repeated-hour labels, keyboard dismissal and reduced motion.
- [x] 4.4 Run `./scripts/lint.sh`, resolve failures introduced by this change, and review the diff for unintended planner/config/schema/docs/runtime-data changes. Do not stage or commit.
- [x] 4.5 Add a parser regression for valid multi-bucket responses whose independently rounded amounts accumulate beyond one fixed tolerance, using per-bucket cumulative deltas and a rounding bound derived from bucket count while continuing to reject malformed discrepancies.
- [x] 4.6 Distinguish cost-series request failures from a valid empty-period response so the chart reports unavailable data truthfully while retaining the validated Actual fallback for unavailable comparisons.
